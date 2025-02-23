
    // Measurement tools test
    module show_bbox(points) {
        min_point = [min([for (p = points) p[0]]), min([for (p = points) p[1]]), min([for (p = points) p[2]])];
        max_point = [max([for (p = points) p[0]]), max([for (p = points) p[1]]), max([for (p = points) p[2]])];
        translate(min_point)
            %cube(max_point - min_point);
    }
    
    module dimension_line(start, end, offset=5) {
        vector = end - start;
        length = norm(vector);
        translate(start)
            rotate([0, 0, atan2(vector[1], vector[0])])
                union() {
                    cylinder(h=length, r=0.5, center=false);
                    translate([0, offset, 0])
                        text(str(length), size=5);
                }
    }
    
    // Test object
    cube(20);
    
    // Show measurements
    points = [[0,0,0], [20,0,0], [20,20,0], [0,20,0]];
    show_bbox(points);
    dimension_line([0,0,0], [20,0,0]);
    