# Spring 2026 research notes

These are the notes from the original reverse engineering, written in March 2026 and published as they were, apart from replacing the robot's serial number, MAC address and MQTT topic with placeholders.

Some of their conclusions have since been overtaken. For example, they treat the camera and map as unsolved. Where these disagree with the [newer notes](../README.md), the newer notes win.

| File | Topic |
|------|-------|
| [01_process_architecture.md](01_process_architecture.md) | Processes on the robot |
| [02_message_protocol.md](02_message_protocol.md) | Message protocol |
| [03_zeromq_services.md](03_zeromq_services.md) | ZeroMQ services |
| [04_mcu_protocol.md](04_mcu_protocol.md) | Serial protocol to the STM32 |
| [05_cloud_protocol.md](05_cloud_protocol.md) | QLCloud protocol |
| [06_proof_of_concept.md](06_proof_of_concept.md) | First proof of concept |
| [08_dispatch_protocol.md](08_dispatch_protocol.md) | Dispatch protocol |
| [11_command_architecture.md](11_command_architecture.md) | How commands travel through the system |
| [12_shm_zmq_camera.md](12_shm_zmq_camera.md) | Shared memory, ZeroMQ and camera research |
| [shm_segments_report.md](shm_segments_report.md) | Shared memory segments |
| [zmq_ipc_topology.md](zmq_ipc_topology.md) | ZeroMQ socket map |

Phases 9 and 10 are in [collab/docs/](../../collab/docs/).
