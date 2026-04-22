import math
import numpy as np

def _matrix_to_euler_xyz(R: np.ndarray) -> list[float]:
    sy = math.sqrt(R[0,0] * R[0,0] +  R[1,0] * R[1,0])
    singular = sy < 1e-6
    if not singular:
        x = math.atan2(R[2,1], R[2,2])
        y = math.atan2(-R[2,0], sy)
        z = math.atan2(R[1,0], R[0,0])
    else:
        x = math.atan2(-R[1,2], R[1,1])
        y = math.atan2(-R[2,0], sy)
        z = 0
    return [math.degrees(x), math.degrees(y), math.degrees(z)]

Rz = np.array([[0.866, -0.5, 0], [0.5, 0.866, 0], [0, 0, 1]])
print("30 deg Z:", _matrix_to_euler_xyz(Rz))

