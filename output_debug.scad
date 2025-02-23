// Original STL Import
import("testobjects/Cube_3d_printing_sample.stl");

// Our SCAD Conversion
%{
  echo("=== Conversion Debug Info ===");
  echo("Original vertices:", 36);
  echo("Optimized vertices:", 8);
  echo("Faces:", 12);
  echo("Reduction:", 77.8, "%");
}

translate([50, 0, 0]) {
// STL to SCAD Conversion
// name: binary stl file                                                                 
// volume: 8000.0
// bbox: ((np.float32(-55.0), np.float32(-35.0)), (np.float32(40.0), np.float32(60.0)), (np.float32(0.0), np.float32(20.0)))

polyhedron(
  points=[
    [-35.000000, 60.000000, 20.000000],
    [-55.000000, 60.000000, 20.000000],
    [-35.000000, 40.000000, 20.000000],
    [-55.000000, 40.000000, 20.000000],
    [-35.000000, 40.000000, 0.000000],
    [-55.000000, 40.000000, 0.000000],
    [-35.000000, 60.000000, 0.000000],
    [-55.000000, 60.000000, 0.000000],
  ],
  faces=[
    [0, 1, 2],
    [2, 1, 3],
    [4, 5, 6],
    [6, 5, 7],
    [3, 5, 2],
    [2, 5, 4],
    [1, 7, 3],
    [3, 7, 5],
    [0, 6, 1],
    [1, 6, 7],
    [2, 4, 0],
    [0, 4, 6],
  ],
  convexity=10
);
}
