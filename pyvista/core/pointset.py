"""Sub-classes and wrappers for vtk.vtkPointSet."""
import pathlib
import logging
import os
import warnings
import numbers
import collections

import numpy as np

import pyvista
from pyvista import _vtk
from pyvista.utilities import abstract_class, assert_empty_kwargs
from pyvista.utilities.cells import (CellArray, numpy_to_idarr,
                                     generate_cell_offsets,
                                     create_mixed_cells,
                                     get_mixed_cells)
from .dataset import DataSet
from .filters import PolyDataFilters, UnstructuredGridFilters, StructuredGridFilters
from ..utilities.fileio import get_ext

log = logging.getLogger(__name__)
log.setLevel('CRITICAL')


class PointSet(DataSet):
    """PyVista's equivalent of vtk.vtkPointSet.

    This holds methods common to PolyData and UnstructuredGrid.
    """

    def center_of_mass(self, scalars_weight=False):
        """Return the coordinates for the center of mass of the mesh.

        Parameters
        ----------
        scalars_weight : bool, optional
            Flag for using the mesh scalars as weights. Defaults to False.

        Returns
        -------
        center : np.ndarray, float
            Coordinates for the center of mass.

        """
        alg = _vtk.vtkCenterOfMass()
        alg.SetInputDataObject(self)
        alg.SetUseScalarsAsWeights(scalars_weight)
        alg.Update()
        return np.array(alg.GetCenter())

    def shallow_copy(self, to_copy):
        """Do a shallow copy the pointset."""
        # Set default points if needed
        if not to_copy.GetPoints():
            to_copy.SetPoints(_vtk.vtkPoints())
        return DataSet.shallow_copy(self, to_copy)

    def remove_cells(self, ind, inplace=True):
        """Remove cells.

        Parameters
        ----------
        ind : iterable
            Cell indices to be removed.  The array can also be a
            boolean array of the same size as the number of cells.

        inplace : bool, optional
            Updates mesh in-place while returning nothing when ``True``.

        Examples
        --------
        Remove first 1000 cells from an unstructured grid.

        >>> import pyvista
        >>> letter_a = pyvista.examples.download_letter_a()
        >>> letter_a.remove_cells(range(1000))
        """
        if isinstance(ind, np.ndarray):
            if ind.dtype == np.bool_ and ind.size != self.n_cells:
                raise ValueError('Boolean array size must match the '
                                 f'number of cells ({self.n_cells}')
        ghost_cells = np.zeros(self.n_cells, np.uint8)
        ghost_cells[ind] = _vtk.vtkDataSetAttributes.DUPLICATECELL

        if inplace:
            target = self
        else:
            target = self.copy()

        target.cell_arrays[_vtk.vtkDataSetAttributes.GhostArrayName()] = ghost_cells
        target.RemoveGhostCells()

        if not inplace:
            return target


class PolyData(_vtk.vtkPolyData, PointSet, PolyDataFilters):
    """Extend the functionality of a vtk.vtkPolyData object.

    Can be initialized in several ways:

    - Create an empty mesh
    - Initialize from a vtk.vtkPolyData
    - Using vertices
    - Using vertices and faces
    - From a file

    Parameters
    ----------
    var_inp : vtk.PolyData, iterable, optional
        Flexible input type.  Can be a ``vtk.PolyData``, in which case
        this PolyData object will be copied if ``deep=True`` and will
        be a shallow copy if ``deep=False``.

        Otherwise, this must be a points array or list containing one
        or more points.  Each point must contain 3 dimensions.

    faces : iterable, optional
        Face connectivity array.  Faces must contain padding
        indicating the number of points in the face.  For example, the
        two faces ``[10, 11, 12]`` and ``[20, 21, 22, 23]`` will be
        represented as ``[3, 10, 11, 12, 4, 20, 21, 22, 23]``.  This
        lets you have an arbitrary number of points per face.

        When not including the face connectivity array, each point
        will be assigned to a single vertex.  This is used for point
        clouds that have no connectivity.

    n_faces : int, optional
        Number of faces in the ``faces`` connectivity array.  While
        optional, setting this speeds up the creation of the
        ``PolyData``.

    lines : iterable, optional
        The line connectivity array.  Like ``faces``, this array
        requires padding indicating the number of points in a line
        segment.  For example, the two line segments ``[0, 1]`` and
        ``[1, 2, 3, 4]`` will be represented as
        ``[2, 0, 1, 4, 1, 2, 3, 4]``

    n_lines : int, optional
        Number of lines in the ``lines`` connectivity array.  While
        optional, setting this speeds up the creation of the
        ``PolyData``.

    deep : bool, optional
        Optional to copy the inputs, or to create a mesh from them
        without copying them.  Setting ``deep=True`` ensures that the
        original arrays can be modified outside the mesh without
        affecting the mesh.

    Examples
    --------
    >>> import vtk
    >>> import numpy as np
    >>> from pyvista import examples
    >>> import pyvista

    Create an empty mesh

    >>> mesh = pyvista.PolyData()

    Initialize from a vtk.vtkPolyData object

    >>> vtkobj = vtk.vtkPolyData()
    >>> mesh = pyvista.PolyData(vtkobj)

    Initialize from just vertices

    >>> vertices = np.array([[0, 0, 0], [1, 0, 0], [1, 0.5, 0], [0, 0.5, 0],])
    >>> mesh = pyvista.PolyData(vertices)

    Initialize from vertices and faces

    >>> faces = np.hstack([[3, 0, 1, 2], [3, 0, 3, 2]])
    >>> mesh = pyvista.PolyData(vertices, faces)

    Initialize from vertices and lines

    >>> lines = np.hstack([[2, 0, 1], [2, 1, 2]])
    >>> mesh = pyvista.PolyData(vertices, lines=lines)

    Initialize from a filename

    >>> mesh = pyvista.PolyData(examples.antfile)

    """

    _READERS = {'.ply': _vtk.vtkPLYReader,
                '.stl': _vtk.vtkSTLReader,
                '.vtk': _vtk.vtkPolyDataReader,
                '.vtp': _vtk.vtkXMLPolyDataReader,
                '.obj': _vtk.vtkOBJReader}
    _WRITERS = {'.ply': _vtk.vtkPLYWriter,
                '.vtp': _vtk.vtkXMLPolyDataWriter,
                '.stl': _vtk.vtkSTLWriter,
                '.vtk': _vtk.vtkPolyDataWriter}

    def __init__(self, var_inp=None, faces=None, n_faces=None, lines=None,
                 n_lines=None, deep=False) -> None:
        """Initialize the polydata."""
        points = None
        local_parms = locals()
        super().__init__()

        # allow empty input
        if var_inp is None:
            return

        # filename
        elif isinstance(var_inp, (str, pathlib.Path)):
            for kwarg in ['faces', 'n_faces', 'lines']:
                if local_parms[kwarg]:
                    raise ValueError('No other arguments should be set when first '
                                     'parameter is a string')
            self._from_file(var_inp)  # is filename

            # When loading files with just point arrays, create and
            # set the polydata vertices
            if self.n_points > 0 and self.n_cells == 0:
                verts = self._make_vertex_cells(self.n_points)
                self.verts = CellArray(verts, self.n_points, deep)

            return

        # PolyData-like
        elif isinstance(var_inp, (PolyData, _vtk.vtkPolyData)):
            for kwarg in ['faces', 'n_faces', 'lines']:
                if local_parms[kwarg]:
                    raise ValueError('No other arguments should be set when first '
                                     'parameter is a PolyData')
            if deep:
                self.deep_copy(var_inp)
            else:
                self.shallow_copy(var_inp)
            return

        # First parameter is points
        elif isinstance(var_inp, (np.ndarray, list)):
            points = var_inp
            if not isinstance(points, np.ndarray):
                points = np.array(points)
            self.SetPoints(pyvista.vtk_points(points, deep=deep))
        else:
            TypeError('Invalid Input type:\n\n'
                      'Expected first argument to be either a:\n'
                      '    - vtk.PolyData\n'
                      '    - pyvista.PolyData\n'
                      '    - numeric numpy.ndarray (1 or 2 dimensions)\n'
                      '    - List (flat or nested with 3 points per vertex)\n\n'
                      f'Instead got: {type(var_inp)}')

        # At this point, points have been setup, add faces and/or lines
        if faces is None and lines is None:
            # one cell per point (point cloud case)
            verts = self._make_vertex_cells(self.n_points)
            self.verts = CellArray(verts, self.n_points, deep)

        elif faces is not None:
            # here we use CellArray since we must specify deep and n_faces
            self.faces = CellArray(faces, n_faces, deep)

        # can always set lines
        if lines is not None:
            # here we use CellArray since we must specify deep and n_lines
            self.lines = CellArray(lines, n_lines, deep)

    def __repr__(self):
        """Return the standard representation."""
        return DataSet.__repr__(self)

    def __str__(self):
        """Return the standard str representation."""
        return DataSet.__str__(self)

    @staticmethod
    def _make_vertex_cells(npoints):
        cells = np.empty((npoints, 2), dtype=pyvista.ID_TYPE)
        cells[:, 0] = 1
        cells[:, 1] = np.arange(npoints, dtype=pyvista.ID_TYPE)
        return cells

    @property
    def verts(self):
        """Get the vertex cells."""
        return _vtk.vtk_to_numpy(self.GetVerts().GetData())

    @verts.setter
    def verts(self, verts):
        """Set the vertex cells."""
        if isinstance(verts, CellArray):
            self.SetVerts(verts)
        else:
            self.SetVerts(CellArray(verts))

    @property
    def lines(self):
        """Return a pointer to the lines as a numpy object."""
        return _vtk.vtk_to_numpy(self.GetLines().GetData()).ravel()

    @lines.setter
    def lines(self, lines):
        """Set the lines of the polydata."""
        if isinstance(lines, CellArray):
            self.SetLines(lines)
        else:
            self.SetLines(CellArray(lines))

    @property
    def faces(self):
        """Return a pointer to the points as a numpy object."""
        return _vtk.vtk_to_numpy(self.GetPolys().GetData())

    @faces.setter
    def faces(self, faces):
        """Set the face cells."""
        if isinstance(faces, CellArray):
            self.SetPolys(faces)
        else:
            self.SetPolys(CellArray(faces))

    def is_all_triangles(self):
        """Return True if all the faces of the polydata are triangles."""
        # Need to make sure there are only face cells and no lines/verts
        if not len(self.faces) or len(self.lines) > 0 or len(self.verts) > 0:
            return False
        # All we have are faces, check if all faces are indeed triangles
        return self.faces.size % 4 == 0 and (self.faces.reshape(-1, 4)[:, 0] == 3).all()

    def __sub__(self, cutting_mesh):
        """Subtract two meshes."""
        return self.boolean_cut(cutting_mesh)

    @property
    def n_faces(self):
        """Return the number of cells.

        Alias for ``n_cells``.

        """
        return self.n_cells

    @property
    def number_of_faces(self):
        """Return the number of cells."""
        return self.n_cells

    def save(self, filename, binary=True):
        """Write a surface mesh to disk.

        Written file may be an ASCII or binary ply, stl, or vtk mesh
        file. If ply or stl format is chosen, the face normals are
        computed in place to ensure the mesh is properly saved.

        Parameters
        ----------
        filename : str
            Filename of mesh to be written.  File type is inferred from
            the extension of the filename unless overridden with
            ftype.  Can be one of the following types (.ply, .stl,
            .vtk)

        binary : bool, optional
            Writes the file as binary when True and ASCII when False.

        Notes
        -----
        Binary files write much faster than ASCII and have a smaller
        file size.

        """
        filename = os.path.abspath(os.path.expanduser(str(filename)))
        ftype = get_ext(filename)
        # Recompute normals prior to save.  Corrects a bug were some
        # triangular meshes are not saved correctly
        if ftype in ['stl', 'ply']:
            self.compute_normals(inplace=True)
        super().save(filename, binary)

    @property
    def area(self):
        """Return the mesh surface area.

        Returns
        -------
        area : float
            Total area of the mesh.

        """
        areas = self.compute_cell_sizes(length=False, area=True, volume=False,)["Area"]
        return np.sum(areas)

    @property
    def volume(self):
        """Return the mesh volume.

        This will throw a VTK error/warning if not a closed surface

        Returns
        -------
        volume : float
            Total volume of the mesh.

        """
        mprop = _vtk.vtkMassProperties()
        mprop.SetInputData(self.triangulate())
        return mprop.GetVolume()

    @property
    def point_normals(self):
        """Return the point normals."""
        mesh = self.compute_normals(cell_normals=False, inplace=False)
        return mesh.point_arrays['Normals']

    @property
    def cell_normals(self):
        """Return the cell normals."""
        mesh = self.compute_normals(point_normals=False, inplace=False)
        return mesh.cell_arrays['Normals']

    @property
    def face_normals(self):
        """Return the cell normals."""
        return self.cell_normals

    @property
    def obbTree(self):
        """Return the obbTree of the polydata.

        An obbTree is an object to generate oriented bounding box (OBB)
        trees. An oriented bounding box is a bounding box that does not
        necessarily line up along coordinate axes. The OBB tree is a
        hierarchical tree structure of such boxes, where deeper levels of OBB
        confine smaller regions of space.
        """
        if not hasattr(self, '_obbTree'):
            self._obbTree = _vtk.vtkOBBTree()
            self._obbTree.SetDataSet(self)
            self._obbTree.BuildLocator()

        return self._obbTree

    @property
    def n_open_edges(self):
        """Return the number of open edges on this mesh."""
        alg = _vtk.vtkFeatureEdges()
        alg.FeatureEdgesOff()
        alg.BoundaryEdgesOn()
        alg.NonManifoldEdgesOn()
        alg.SetInputDataObject(self)
        alg.Update()
        return alg.GetOutput().GetNumberOfCells()

    def __del__(self):
        """Delete the object."""
        if hasattr(self, '_obbTree'):
            del self._obbTree


@abstract_class
class PointGrid(PointSet):
    """Class in common with structured and unstructured grids."""

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the point grid."""
        super().__init__()

    def plot_curvature(self, curv_type='mean', **kwargs):
        """Plot the curvature of the external surface of the grid.

        Parameters
        ----------
        curv_type : str, optional
            One of the following strings indicating curvature types

            - mean
            - gaussian
            - maximum
            - minimum

        **kwargs : optional
            Optional keyword arguments.  See help(pyvista.plot)

        Returns
        -------
        cpos : list
            Camera position, focal point, and view up.  Used for storing and
            setting camera view.

        """
        trisurf = self.extract_surface().triangulate()
        return trisurf.plot_curvature(curv_type, **kwargs)

    @property
    def volume(self):
        """Compute the volume of the point grid.

        This extracts the external surface and computes the interior volume
        """
        surf = self.extract_surface().triangulate()
        return surf.volume


class UnstructuredGrid(_vtk.vtkUnstructuredGrid, PointGrid, UnstructuredGridFilters):
    """
    Extends the functionality of a vtk.vtkUnstructuredGrid object.

    Can be initialized by the following:

    - Creating an empty grid
    - From a vtk.vtkPolyData object
    - From cell, offset, and node arrays
    - From a file

    Examples
    --------
    >>> import pyvista
    >>> from pyvista import examples
    >>> import vtk

    Create an empty grid

    >>> grid = pyvista.UnstructuredGrid()

    Copy a vtkUnstructuredGrid

    >>> vtkgrid = vtk.vtkUnstructuredGrid()
    >>> grid = pyvista.UnstructuredGrid(vtkgrid)  # Initialize from a vtkUnstructuredGrid

    >>> # from arrays (vtk9)
    >>> #grid = pyvista.UnstructuredGrid(cells, celltypes, points)

    >>> # from arrays (vtk<9)
    >>> #grid = pyvista.UnstructuredGrid(offset, cells, celltypes, points)

    From a string filename

    >>> grid = pyvista.UnstructuredGrid(examples.hexbeamfile)

    """

    _READERS = {'.vtu': _vtk.vtkXMLUnstructuredGridReader,
                '.vtk': _vtk.vtkUnstructuredGridReader}
    _WRITERS = {'.vtu': _vtk.vtkXMLUnstructuredGridWriter,
                '.vtk': _vtk.vtkUnstructuredGridWriter}

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the unstructured grid."""
        super().__init__()
        deep = kwargs.pop('deep', False)

        if not len(args):
            return
        if len(args) == 1:
            if isinstance(args[0], _vtk.vtkUnstructuredGrid):
                if deep:
                    self.deep_copy(args[0])
                else:
                    self.shallow_copy(args[0])

            elif isinstance(args[0], (str, pathlib.Path)):
                self._from_file(args[0])

            elif isinstance(args[0], _vtk.vtkStructuredGrid):
                vtkappend = _vtk.vtkAppendFilter()
                vtkappend.AddInputData(args[0])
                vtkappend.Update()
                self.shallow_copy(vtkappend.GetOutput())

            else:
                itype = type(args[0])
                raise TypeError(f'Cannot work with input type {itype}')

        # Cell dictionary creation
        elif len(args) == 2 and isinstance(args[0], dict) and isinstance(args[1], np.ndarray):
            self._from_cells_dict(args[0], args[1], deep)
            self._check_for_consistency()

        elif len(args) == 3:  # and VTK9:
            arg0_is_arr = isinstance(args[0], np.ndarray)
            arg1_is_arr = isinstance(args[1], np.ndarray)
            arg2_is_arr = isinstance(args[2], np.ndarray)

            if all([arg0_is_arr, arg1_is_arr, arg2_is_arr]):
                self._from_arrays(None, args[0], args[1], args[2], deep)
                self._check_for_consistency()
            else:
                raise TypeError('All input types must be np.ndarray')

        elif len(args) == 4:
            arg0_is_arr = isinstance(args[0], np.ndarray)
            arg1_is_arr = isinstance(args[1], np.ndarray)
            arg2_is_arr = isinstance(args[2], np.ndarray)
            arg3_is_arr = isinstance(args[3], np.ndarray)

            if all([arg0_is_arr, arg1_is_arr, arg2_is_arr, arg3_is_arr]):
                self._from_arrays(args[0], args[1], args[2], args[3], deep)
                self._check_for_consistency()
            else:
                raise TypeError('All input types must be np.ndarray')

        else:
            err_msg = 'Invalid parameters.  Initialization with arrays ' +\
                      'requires the following arrays:\n'
            if _vtk.VTK9:
                raise TypeError(err_msg + '`cells`, `cell_type`, `points`')
            else:
                raise TypeError(err_msg + '(`offset` optional), `cells`, `cell_type`, `points`')

    def __repr__(self):
        """Return the standard representation."""
        return DataSet.__repr__(self)

    def __str__(self):
        """Return the standard str representation."""
        return DataSet.__str__(self)

    def _from_cells_dict(self, cells_dict, points, deep=True):
        if points.ndim != 2 or points.shape[-1] != 3:
            raise ValueError("Points array must be a [M, 3] array")

        nr_points = points.shape[0]
        if _vtk.VTK9:
            cell_types, cells = create_mixed_cells(cells_dict, nr_points)
            self._from_arrays(None, cells, cell_types, points, deep=deep)
        else:
            cell_types, cells, offset = create_mixed_cells(cells_dict, nr_points)
            self._from_arrays(offset, cells, cell_types, points, deep=deep)



    def _from_arrays(self, offset, cells, cell_type, points, deep=True):
        """Create VTK unstructured grid from numpy arrays.

        Parameters
        ----------
        offset : np.ndarray dtype=np.int64
            Array indicating the start location of each cell in the cells
            array.  Set to ``None`` when using VTK 9+.

        cells : np.ndarray dtype=np.int64
            Array of cells.  Each cell contains the number of points in the
            cell and the node numbers of the cell.

        cell_type : np.uint8
            Cell types of each cell.  Each cell type numbers can be found from
            vtk documentation.  See example below.

        points : np.ndarray
            Numpy array containing point locations.

        Examples
        --------
        >>> import numpy
        >>> import vtk
        >>> import pyvista
        >>> offset = np.array([0, 9])
        >>> cells = np.array([8, 0, 1, 2, 3, 4, 5, 6, 7, 8, 8, 9, 10, 11, 12, 13, 14, 15])
        >>> cell_type = np.array([vtk.VTK_HEXAHEDRON, vtk.VTK_HEXAHEDRON], np.int8)

        >>> cell1 = np.array([[0, 0, 0],
        ...                   [1, 0, 0],
        ...                   [1, 1, 0],
        ...                   [0, 1, 0],
        ...                   [0, 0, 1],
        ...                   [1, 0, 1],
        ...                   [1, 1, 1],
        ...                   [0, 1, 1]])

        >>> cell2 = np.array([[0, 0, 2],
        ...                   [1, 0, 2],
        ...                   [1, 1, 2],
        ...                   [0, 1, 2],
        ...                   [0, 0, 3],
        ...                   [1, 0, 3],
        ...                   [1, 1, 3],
        ...                   [0, 1, 3]])

        >>> points = np.vstack((cell1, cell2))

        >>> grid = pyvista.UnstructuredGrid(offset, cells, cell_type, points)

        """
        # Convert to vtk arrays
        vtkcells = CellArray(cells, cell_type.size, deep)
        if cell_type.dtype != np.uint8:
            cell_type = cell_type.astype(np.uint8)
        cell_type_np = cell_type
        cell_type = _vtk.numpy_to_vtk(cell_type, deep=deep)

        # Convert points to vtkPoints object
        points = pyvista.vtk_points(points, deep=deep)
        self.SetPoints(points)

        # vtk9 does not require an offset array
        if _vtk.VTK9:
            if offset is not None:
                warnings.warn('VTK 9 no longer accepts an offset array',
                              stacklevel=3)
            self.SetCells(cell_type, vtkcells)
        else:
            if offset is None:
                offset = generate_cell_offsets(cells, cell_type_np)

            self.SetCells(cell_type, numpy_to_idarr(offset), vtkcells)

    def _check_for_consistency(self):
        """Check if size of offsets and celltypes match the number of cells.

        Checks if the number of offsets and celltypes correspond to
        the number of cells.  Called after initialization of the self
        from arrays.
        """
        if self.n_cells != self.celltypes.size:
            raise ValueError(f'Number of cell types ({self.celltypes.size}) '
                             f'must match the number of cells {self.n_cells})')

        if _vtk.VTK9:
            if self.n_cells != self.offset.size - 1:
                raise ValueError(f'Size of the offset ({self.offset.size}) '
                                 'must be one greater than the number of cells '
                                 f'({self.n_cells})')
        else:
            if self.n_cells != self.offset.size:
                raise ValueError(f'Size of the offset ({self.offset.size}) '
                                 f'must match the number of cells ({self.n_cells})')

    @property
    def cells(self):
        """Legacy method: Return a pointer to the cells as a numpy object."""
        return _vtk.vtk_to_numpy(self.GetCells().GetData())

    @property
    def cells_dict(self):
        """Return a dictionary that contains all cells mapped from cell types.

        This function returns a np.ndarray for each cell type in an ordered fashion.
        Note that this function only works with element types of fixed sizes

        Returns
        -------
        cells_dict : dict
            A dictionary mapping containing all cells of this unstructured grid.
            Structure: vtk_enum_type (int) -> cells (np.ndarray)

        """
        return get_mixed_cells(self)

    @property
    def cell_connectivity(self):
        """Return a the vtk cell connectivity as a numpy array."""
        carr = self.GetCells()
        if _vtk.VTK9:
            return _vtk.vtk_to_numpy(carr.GetConnectivityArray())
        raise AttributeError('Install vtk>=9.0.0 for `cell_connectivity`\n'
                             'Otherwise, use the legacy `cells` method')

    def linear_copy(self, deep=False):
        """Return a copy of the unstructured grid containing only linear cells.

        Converts the following cell types to their linear equivalents.

        - VTK_QUADRATIC_TETRA      --> VTK_TETRA
        - VTK_QUADRATIC_PYRAMID    --> VTK_PYRAMID
        - VTK_QUADRATIC_WEDGE      --> VTK_WEDGE
        - VTK_QUADRATIC_HEXAHEDRON --> VTK_HEXAHEDRON

        Parameters
        ----------
        deep : bool
            When True, makes a copy of the points array.  Default
            False.  Cells and cell types are always copied.

        Returns
        -------
        grid : pyvista.UnstructuredGrid
            UnstructuredGrid containing only linear cells.

        """
        lgrid = self.copy(deep)

        # grab the vtk object
        vtk_cell_type = _vtk.numpy_to_vtk(self.GetCellTypesArray(), deep=True)
        celltype = _vtk.vtk_to_numpy(vtk_cell_type)
        celltype[celltype == _vtk.VTK_QUADRATIC_TETRA] = _vtk.VTK_TETRA
        celltype[celltype == _vtk.VTK_QUADRATIC_PYRAMID] = _vtk.VTK_PYRAMID
        celltype[celltype == _vtk.VTK_QUADRATIC_WEDGE] = _vtk.VTK_WEDGE
        celltype[celltype == _vtk.VTK_QUADRATIC_HEXAHEDRON] = _vtk.VTK_HEXAHEDRON

        # track quad mask for later
        quad_quad_mask = celltype == _vtk.VTK_QUADRATIC_QUAD
        celltype[quad_quad_mask] = _vtk.VTK_QUAD

        quad_tri_mask = celltype == _vtk.VTK_QUADRATIC_TRIANGLE
        celltype[quad_tri_mask] = _vtk.VTK_TRIANGLE

        vtk_offset = self.GetCellLocationsArray()
        cells = _vtk.vtkCellArray()
        cells.DeepCopy(self.GetCells())
        lgrid.SetCells(vtk_cell_type, vtk_offset, cells)

        # fixing bug with display of quad cells
        if np.any(quad_quad_mask):
            if _vtk.VTK9:
                quad_offset = lgrid.offset[:-1][quad_quad_mask]
                base_point = lgrid.cell_connectivity[quad_offset]
                lgrid.cell_connectivity[quad_offset + 4] = base_point
                lgrid.cell_connectivity[quad_offset + 5] = base_point
                lgrid.cell_connectivity[quad_offset + 6] = base_point
                lgrid.cell_connectivity[quad_offset + 7] = base_point
            else:
                quad_offset = lgrid.offset[quad_quad_mask]
                base_point = lgrid.cells[quad_offset + 1]
                lgrid.cells[quad_offset + 5] = base_point
                lgrid.cells[quad_offset + 6] = base_point
                lgrid.cells[quad_offset + 7] = base_point
                lgrid.cells[quad_offset + 8] = base_point

        if np.any(quad_tri_mask):
            if _vtk.VTK9:
                tri_offset = lgrid.offset[:-1][quad_tri_mask]
                base_point = lgrid.cell_connectivity[tri_offset]
                lgrid.cell_connectivity[tri_offset + 3] = base_point
                lgrid.cell_connectivity[tri_offset + 4] = base_point
                lgrid.cell_connectivity[tri_offset + 5] = base_point
            else:
                tri_offset = lgrid.offset[quad_tri_mask]
                base_point = lgrid.cells[tri_offset + 1]
                lgrid.cells[tri_offset + 4] = base_point
                lgrid.cells[tri_offset + 5] = base_point
                lgrid.cells[tri_offset + 6] = base_point

        return lgrid

    @property
    def celltypes(self):
        """Get the cell types array."""
        return _vtk.vtk_to_numpy(self.GetCellTypesArray())

    @property
    def offset(self):
        """Get cell locations Array."""
        carr = self.GetCells()
        if _vtk.VTK9:
            # This will be the number of cells + 1.
            return _vtk.vtk_to_numpy(carr.GetOffsetsArray())
        else:  # this is no longer used in >= VTK9
            return _vtk.vtk_to_numpy(self.GetCellLocationsArray())


class StructuredGrid(_vtk.vtkStructuredGrid, PointGrid, StructuredGridFilters):
    """Extend the functionality of a vtk.vtkStructuredGrid object.

    Can be initialized in several ways:

    - Create empty grid
    - Initialize from a vtk.vtkStructuredGrid object
    - Initialize directly from the point arrays

    See _from_arrays in the documentation for more details on initializing
    from point arrays

    Examples
    --------
    >>> import pyvista
    >>> import vtk
    >>> import numpy as np

    >>> # Create empty grid
    >>> grid = pyvista.StructuredGrid()

    >>> # Initialize from a vtk.vtkStructuredGrid object
    >>> vtkgrid = vtk.vtkStructuredGrid()
    >>> grid = pyvista.StructuredGrid(vtkgrid)

    >>> # Create from NumPy arrays
    >>> xrng = np.arange(-10, 10, 2)
    >>> yrng = np.arange(-10, 10, 2)
    >>> zrng = np.arange(-10, 10, 2)
    >>> x, y, z = np.meshgrid(xrng, yrng, zrng)
    >>> grid = pyvista.StructuredGrid(x, y, z)

    """

    _READERS = {'.vtk': _vtk.vtkStructuredGridReader,
                '.vts': _vtk.vtkXMLStructuredGridReader}
    _WRITERS = {'.vtk': _vtk.vtkStructuredGridWriter,
                '.vts': _vtk.vtkXMLStructuredGridWriter}

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the structured grid."""
        super().__init__()

        if len(args) == 1:
            if isinstance(args[0], _vtk.vtkStructuredGrid):
                self.deep_copy(args[0])
            elif isinstance(args[0], str):
                self._from_file(args[0])

        elif len(args) == 3:
            arg0_is_arr = isinstance(args[0], np.ndarray)
            arg1_is_arr = isinstance(args[1], np.ndarray)
            arg2_is_arr = isinstance(args[2], np.ndarray)

            if all([arg0_is_arr, arg1_is_arr, arg2_is_arr]):
                self._from_arrays(args[0], args[1], args[2])

    def __repr__(self):
        """Return the standard representation."""
        return DataSet.__repr__(self)

    def __str__(self):
        """Return the standard str representation."""
        return DataSet.__str__(self)

    def _from_arrays(self, x, y, z):
        """Create VTK structured grid directly from numpy arrays.

        Parameters
        ----------
        x : np.ndarray
            Position of the points in x direction.

        y : np.ndarray
            Position of the points in y direction.

        z : np.ndarray
            Position of the points in z direction.

        """
        if not(x.shape == y.shape == z.shape):
            raise ValueError('Input point array shapes must match exactly')

        # make the output points the same precision as the input arrays
        points = np.empty((x.size, 3), x.dtype)
        points[:, 0] = x.ravel('F')
        points[:, 1] = y.ravel('F')
        points[:, 2] = z.ravel('F')

        # ensure that the inputs are 3D
        dim = list(x.shape)
        while len(dim) < 3:
            dim.append(1)

        # Create structured grid
        self.SetDimensions(dim)
        self.SetPoints(pyvista.vtk_points(points))

    @property
    def dimensions(self):
        """Return a length 3 tuple of the grid's dimensions."""
        return list(self.GetDimensions())

    @dimensions.setter
    def dimensions(self, dims):
        """Set the dataset dimensions. Pass a length three tuple of integers."""
        nx, ny, nz = dims[0], dims[1], dims[2]
        self.SetDimensions(nx, ny, nz)
        self.Modified()

    @property
    def x(self):
        """Return the X coordinates of all points."""
        return self._reshape_point_array(self.points[:, 0])

    @property
    def y(self):
        """Return the Y coordinates of all points."""
        return self._reshape_point_array(self.points[:, 1])

    @property
    def z(self):
        """Return the Z coordinates of all points."""
        return self._reshape_point_array(self.points[:, 2])

    @property
    def points_matrix(self):
        """Points as a 4-D matrix, with x/y/z along the last dimension."""
        return self.points.reshape((*self.dimensions, 3), order='F')

    def _get_attrs(self):
        """Return the representation methods (internal helper)."""
        attrs = PointGrid._get_attrs(self)
        attrs.append(("Dimensions", self.dimensions, "{:d}, {:d}, {:d}"))
        return attrs

    def __getitem__(self, key):
        """Slice subsets of the StructuredGrid, or extract an array field."""
        # legacy behavior which looks for a point or cell array
        if not isinstance(key, tuple):
            return super().__getitem__(key)

        # convert slice to VOI specification - only "basic indexing" is supported
        voi = []
        rate = []
        if len(key) != 3:
            raise RuntimeError('Slices must have exactly 3 dimensions.')
        for i, k in enumerate(key):
            if isinstance(k, collections.Iterable):
                raise RuntimeError('Fancy indexing is not supported.')
            if isinstance(k, numbers.Integral):
                start = stop = k
                step = 1
            elif isinstance(k, slice):
                start = k.start if k.start is not None else 0
                stop = k.stop - 1 if k.stop is not None else self.dimensions[i]
                step = k.step if k.step is not None else 1
            voi.extend((start, stop))
            rate.append(step)

        return self.extract_subset(voi, rate, boundary=False)

    def hide_cells(self, ind):
        """Hide cells without deleting them.

        Hides cells by setting the ghost_cells array to HIDDEN_CELL.

        Parameters
        ----------
        ind : iterable
            List or array of cell indices to be hidden.  The array can
            also be a boolean array of the same size as the number of
            cells.

        Examples
        --------
        Hide part of the middle of a structured surface.

        >>> import pyvista as pv
        >>> import numpy as np
        >>> x = np.arange(-10, 10, 0.25)
        >>> y = np.arange(-10, 10, 0.25)
        >>> z = 0
        >>> x, y, z = np.meshgrid(x, y, z)
        >>> grid = pv.StructuredGrid(x, y, z)
        >>> grid.hide_cells(range(79*30, 79*50))
        """
        if isinstance(ind, np.ndarray):
            if ind.dtype == np.bool_ and ind.size != self.n_cells:
                raise ValueError('Boolean array size must match the '
                                 f'number of cells ({self.n_cells})')
        ghost_cells = np.zeros(self.n_cells, np.uint8)
        ghost_cells[ind] = _vtk.vtkDataSetAttributes.HIDDENCELL

        # NOTE: cells cannot be removed from a structured grid, only
        # hidden setting ghost_cells to a value besides
        # vtk.vtkDataSetAttributes.HIDDENCELL will not hide them
        # properly, additionally, calling self.RemoveGhostCells will
        # have no effect

        self.cell_arrays[_vtk.vtkDataSetAttributes.GhostArrayName()] = ghost_cells

    def _reshape_point_array(self, array):
        """Reshape point data to a 3-D matrix."""
        return array.reshape(self.dimensions, order='F')

    def _reshape_cell_array(self, array):
        """Reshape cell data to a 3-D matrix."""
        cell_dims = np.array(self.dimensions) - 1
        cell_dims[cell_dims == 0] = 1
        return array.reshape(cell_dims, order='F')
