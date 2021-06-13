"""
Rotations
~~~~~~~~~

Rotations of a cow about her axes. In this model, the x axis is from the left
to right; the y axis is from bottom to top; and the z axis emerges from the
image. The camera location is the same in all four images.

"""
# sphinx_gallery_thumbnail_number = 6
import pyvista as pv
from pyvista import examples

###############################################################################
# Define camera and axes
# ++++++++++++++++++++++
#
# Define camera and axes. Setting axes origin to (1.0, 1.0, 1.0).

mesh = examples.download_cow()

camera = pv.Camera()
camera.position = (30.0, 30.0, 30.0)
camera.focal_point = (5.0, 5.0, 5.0)

axes = pv.Axes(show_actor=True)
axes.origin = (3.0, 3.0, 3.0)

###############################################################################
# Original Mesh
# +++++++++++++
#
# Plot original mesh. Set axes actor to Plotter.

p = pv.Plotter()

p.add_text("Mesh", font_size=24)
p.add_actor(axes.actor)
p.camera = camera
p.add_mesh(mesh)

p.show()

###############################################################################
# Rotate about x axis
# +++++++++++++++++++
#
# Plot meshs rotated about x axis. It is plotted every 60 degrees.
# Set axes actor to Plotter and set axes origin to the point to rotate.

p = pv.Plotter()

p.add_text("X axis rotate", font_size=24)
p.add_actor(axes.actor)
p.camera = camera

for i in range(6):
    rot = mesh.copy()
    rot.rotate_x(60*i, point=axes.origin)
    p.add_mesh(rot)

p.show()

###############################################################################
# Rotate about y axis
# +++++++++++++++++++
#
# Plot meshs rotated about y axis. It is plotted every 60 degrees.
# Set axes actor to Plotter and set axes origin to the point to rotate.

p = pv.Plotter()

p.add_text("Y axis rotate", font_size=24)
p.camera = camera
p.add_actor(axes.actor)

for i in range(6):
    rot = mesh.copy()
    rot.rotate_y(60*i, point=axes.origin)
    p.add_mesh(rot)

p.show()

###############################################################################
# Rotate about z axis
# +++++++++++++++++++
#
# Plot meshs rotated about z axis. It is plotted every 60 degrees.
# Set axes actor to Plotter and set axes origin to the point to rotate.

p = pv.Plotter()

p.add_text("Z axis rotate", font_size=24)
p.camera = camera
p.add_actor(axes.actor)

for i in range(6):
    rot = mesh.copy()
    rot.rotate_z(60*i, point=axes.origin)
    p.add_mesh(rot)

p.show()

###############################################################################
# Rotate about custom vector
# ++++++++++++++++++++++++++
#
# Plot meshs rotated about custom vector. It is plotted every 60 degrees.
# Set axes actor to Plotter and set axes origin to the point to rotate.

p = pv.Plotter()

p.add_text("Custom vector rotate", font_size=24)
p.camera = camera
p.add_actor(axes.actor)
for i in range(6):
    rot = mesh.copy()
    rot.rotate_vector(vector=(1, 1, 1), angle=60*i, point=axes.origin)
    p.add_mesh(rot)

p.show()
