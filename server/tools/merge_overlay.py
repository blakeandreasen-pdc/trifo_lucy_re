import sys, math; sys.path.insert(0,'.')
import numpy as np, map_merge as mm
from PIL import Image
main=mm.PbMap.load('merge_work/maps/maps/_guard/pose_graph_map.pbstream')
piece=mm.PbMap.load('merge_work/piece_hallway_20261029.pbstream')
wA,fA=mm.wall_points(main); wB,fB=mm.wall_points(piece)
lo=np.minimum(wA.min(0),wB.min(0))-2; hi=np.maximum(wA.max(0),wB.max(0))+2
R=0.05; sh=tuple(((hi-lo)/R).astype(int)+1)
def tf(P,T):
    c,s=math.cos(T[2]),math.sin(T[2]); return np.stack([T[0]+c*P[:,0]-s*P[:,1],T[1]+s*P[:,0]+c*P[:,1]],1)
def draw(T):
    img=np.full(sh+(3,),70,np.uint8)
    def put(P,col):
        k=((P-lo)/R).astype(int); img[k[:,0],k[:,1]]=col
    put(fA,(200,200,200)); put(tf(fB,T),(150,200,255)); put(wA,(0,0,0)); put(tf(wB,T),(230,40,40))
    return Image.fromarray(img[::-1,::-1].copy())    # same orientation as map_preview
ims=[draw((0,0,0)), draw((-0.839,-0.256,math.radians(12.7)))]
w=ims[0].width; c=Image.new('RGB',(w*2+10,ims[0].height),(30,30,30)); c.paste(ims[0],(0,0)); c.paste(ims[1],(w+10,0))
c.resize((c.width*2,c.height*2)).save('merge_work/hall_overlay.png')
