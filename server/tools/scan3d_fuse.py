"""3D scanner: align a stretch of a capture with ICP (shape only, no markers or IMU) and fuse it into
one mesh with a TSDF. Runs in WSL with Open3D:
  ~/scan3d-venv/bin/python tools/scan3d_fuse.py <dir> <t_start> <t_end> [voxel_mm] [max_z_m] [out_name]
Writes <out_name>.ply (mesh) and <out_name>.png (three shaded views) in <dir>."""
import sys
from pathlib import Path

import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan3d_read import H, W, records  # noqa: E402

FX, CX, CY = 210.911, 112.161, 85.388  # depth_cam in calib_lucy.json


def load(root, a, b):
    rays, frames, t0 = None, [], None
    for tag, ts, v in records(root / "stream.bin"):
        t0 = t0 or ts
        t = (ts - t0) / 1e6
        if tag == "P":  # a pixel's ray is fixed; any frame where it was valid gives it
            if rays is None:
                rays = (np.full((H, W), np.nan), np.full((H, W), np.nan))
            z = v[..., 2]
            good = z > 0
            rays[0][good], rays[1][good] = v[..., 0][good] / z[good], v[..., 1][good] / z[good]
        elif tag == "D" and a <= t <= b:
            frames.append((t, np.array(v["z"]), np.array(v["conf"])))
    return rays, frames


def clean(z, conf, zmax):
    z = z.copy()
    z[(conf < 200) | (z > zmax)] = 0
    # flying pixels: drop anything far from its neighbours relative to its distance
    d = np.zeros_like(z)
    for ax, s in ((0, 1), (0, -1), (1, 1), (1, -1)):
        d = np.maximum(d, np.abs(z - np.roll(z, s, ax)))
    z[d > np.maximum(0.015, 0.04 * z)] = 0
    return z


def cloud(z, rays):
    ok = (z > 0) & np.isfinite(rays[0]) & np.isfinite(rays[1])
    pts = np.c_[rays[0][ok] * z[ok], rays[1][ok] * z[ok], z[ok]]
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    return pc


def pinhole_depth(z, rays):
    """the cloud's rays are undistorted: resample onto a true pinhole image for the TSDF"""
    ok = (z > 0) & np.isfinite(rays[0]) & np.isfinite(rays[1])
    u = np.round(FX * rays[0][ok] + CX).astype(int)
    v = np.round(FX * rays[1][ok] + CY).astype(int)
    keep = (u >= 0) & (u < W) & (v >= 0) & (v < H)
    out = np.zeros((H, W), np.float32)
    out[v[keep], u[keep]] = z[ok][keep]
    return out


def main():
    root = Path(sys.argv[1])
    a, b = float(sys.argv[2]), float(sys.argv[3])
    vox = float(sys.argv[4]) / 1000 if len(sys.argv) > 4 else 0.003
    zmax = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
    name = sys.argv[6] if len(sys.argv) > 6 else "fused"
    rays, frames = load(root, a, b)
    print(f"{len(frames)} frames, t {a}-{b}")
    icp_vox = max(vox * 1.5, 0.004)
    pose = np.eye(4)
    step = np.eye(4)
    key_pc, key_pose = None, np.eye(4)
    poses, fits, used = [], [], []
    for t, z, conf in frames:
        zc = clean(z, conf, zmax)
        pc = cloud(zc, rays).voxel_down_sample(icp_vox)
        pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=icp_vox * 4, max_nn=30))
        if len(pc.points) < 1500:
            continue
        if key_pc is None:
            key_pc, key_pose = pc, np.eye(4)
            poses.append(np.eye(4)); fits.append(1); used.append(zc)
            continue
        init = np.linalg.inv(key_pose) @ pose @ step
        crit = o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=40)
        est = o3d.pipelines.registration.TransformationEstimationPointToPlane(o3d.pipelines.registration.TukeyLoss(k=0.01))
        res = o3d.pipelines.registration.registration_icp(pc, key_pc, 0.04, init, est, crit)
        res = o3d.pipelines.registration.registration_icp(pc, key_pc, 0.012, res.transformation, est, crit)
        if res.fitness < 0.45:
            print(f"  t={t:.1f} weak fit {res.fitness:.2f}, skipped")
            continue
        new = key_pose @ res.transformation
        step = np.linalg.inv(pose) @ new
        pose = new
        poses.append(pose); fits.append(res.fitness); used.append(zc)
        moved = np.linalg.norm((np.linalg.inv(key_pose) @ pose)[:3, 3])
        ang = np.degrees(np.arccos(np.clip((np.trace((np.linalg.inv(key_pose) @ pose)[:3, :3]) - 1) / 2, -1, 1)))
        if moved > 0.03 or ang > 5 or res.fitness < 0.7:
            key_pc, key_pose = pc, pose
    print(f"aligned {len(poses)}; fitness median {np.median(fits):.2f}; path length {sum(np.linalg.norm(poses[i + 1][:3, 3] - poses[i][:3, 3]) for i in range(len(poses) - 1)):.2f} m")
    dev = o3d.core.Device("CPU:0")
    vbg = o3d.t.geometry.VoxelBlockGrid(attr_names=("tsdf", "weight"), attr_dtypes=(o3d.core.float32, o3d.core.float32),
                                        attr_channels=((1), (1)), voxel_size=vox, block_resolution=16, block_count=60000, device=dev)
    K = o3d.core.Tensor([[FX, 0, CX], [0, FX, CY], [0, 0, 1]], o3d.core.float64)
    for T, zc in zip(poses, used):
        d = o3d.t.geometry.Image(o3d.core.Tensor(pinhole_depth(zc, rays)[..., None].copy()))
        E = o3d.core.Tensor(np.linalg.inv(T), o3d.core.float64)
        blocks = vbg.compute_unique_block_coordinates(d, K, E, 1.0, zmax)
        vbg.integrate(blocks, d, K, E, 1.0, zmax)
    mesh = vbg.extract_triangle_mesh(weight_threshold=3.0).to_legacy()
    mesh.compute_vertex_normals()
    lab, cnt, _ = mesh.cluster_connected_triangles()
    lab, cnt = np.asarray(lab), np.asarray(cnt)
    mesh.remove_triangles_by_mask(cnt[lab] < 2000)
    mesh.remove_unreferenced_vertices()
    print("mesh", len(mesh.vertices), "verts", len(mesh.triangles), "tris; extent m", np.round(mesh.get_max_bound() - mesh.get_min_bound(), 3))
    o3d.io.write_triangle_mesh(str(root / f"{name}.ply"), mesh)
    np.save(root / f"{name}_poses.npy", np.array(poses))
    shade(mesh, root / f"{name}.png", np.array(poses))


def shade(mesh, path, poses):
    """three simple software renders (normal-shaded, z-buffered triangles' vertices), no display needed"""
    from PIL import Image
    V = np.asarray(mesh.vertices)
    N = np.asarray(mesh.vertex_normals)
    c = np.median(V, 0)
    views = []
    start = poses[len(poses) // 2][:3, :3]
    for yaw, pitch in ((0, 0), (40, 15), (-40, 15)):
        ya, pa = np.radians(yaw), np.radians(pitch)
        Ry = np.array([[np.cos(ya), 0, np.sin(ya)], [0, 1, 0], [-np.sin(ya), 0, np.cos(ya)]])
        Rx = np.array([[1, 0, 0], [0, np.cos(pa), -np.sin(pa)], [0, np.sin(pa), np.cos(pa)]])
        R = Rx @ Ry @ start.T
        p = (R @ (V - c).T).T
        n = (R @ N.T).T
        scale = 640 / max(np.ptp(p[:, 0]), np.ptp(p[:, 1]), 1e-3) * 0.9
        S = 720
        x = np.round(S / 2 + p[:, 0] * scale).astype(int)
        y = np.round(S / 2 + p[:, 1] * scale).astype(int)
        zb = np.full((S, S), np.inf)
        img = np.full((S, S), 25, np.uint8)
        light = np.array([-0.4, -0.5, -0.76])
        sh = np.clip(np.abs(n @ light), 0, 1) * 215 + 35
        r = max(1, int(np.ceil(scale * 0.0018)))
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                xx, yy = x + dx, y + dy
                m = (xx >= 0) & (xx < S) & (yy >= 0) & (yy < S)
                order = np.argsort(-p[m, 2])
                xi, yi, zi, si = xx[m][order], yy[m][order], p[m, 2][order], sh[m][order]
                better = zi < zb[yi, xi]
                xi, yi, zi, si = xi[better], yi[better], zi[better], si[better]
                zb[yi, xi] = zi
                img[yi, xi] = si.astype(np.uint8)
        views.append(img)
    Image.fromarray(np.hstack(views)).save(path)


if __name__ == "__main__":
    main()
