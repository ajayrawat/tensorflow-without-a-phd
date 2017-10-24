# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from builtins import zip
import tensorflow as tf

def one_d_intersect(px1, px2, qx1, qx2):
    # this assumes px2>=px1 and qx2>=qx1

    # force broadcasting
    px1 = tf.add(px1, qx1-qx1)
    px2 = tf.add(px2, qx2-qx2)
    zeros = tf.subtract(px1, px1)

    interA = tf.greater(px1, qx1)
    interB = tf.greater(px2, qx1)
    interC = tf.greater(px2, qx2)
    interD = tf.greater(qx2, px1)
    inter = tf.logical_and(interB, interD)

    inter_x1 = tf.where(tf.logical_and(tf.logical_not(interA), interB), qx1, px1)
    inter_x2 = tf.where(tf.logical_and(interC, interD), qx2, px2)
    inter_w = inter_x2 - inter_x1
    inter_w = tf.where(inter, inter_w, zeros)  # for consistency
    return inter, inter_x1, inter_w

def boxintersect(primeroi, rois, min_intersect=0):
    # primeroi: single region shape=[4] Tensor: [x1, y1, x2, y2]
    # rois: multiple regions shape=[n, 4] Tensor: n x [x1, y1, x2, y2]
    # min_intersect: value between 0 and 1.
    #   area(intersection) >= min_intersect * min(area(primeroi), area(roi)) to count as intersection
    # return value: [n] Tensor type bool indicating which rois intersect the primeroi

    px1, py1, px2, py2 = tf.unstack(primeroi, axis=0)
    x1, y1, x2, y2 = tf.unstack(rois, axis=1)
    is_inter_x, inter_x, inter_w = one_d_intersect(px1, px2, x1, x2)
    is_inter_y, inter_y, inter_h = one_d_intersect(py1, py2, y1, y2)
    inter_area = inter_w * inter_h
    parea = (px2-px1)*(py2-py1)
    areas = (x2-x1)*(y2-y1)
    min_areas = tf.minimum(areas, parea)
    inter = tf.logical_and(is_inter_x, is_inter_y)
    inter_with_area = tf.greater_equal(inter_area, min_areas*min_intersect)
    return tf.logical_and(inter, inter_with_area)

def gen_grid(grid_n):
    cell_x = tf.range(0, grid_n, dtype=tf.float32)
    cell_x = tf.tile(tf.expand_dims(cell_x, axis=0), [grid_n, 1])
    cell_x = cell_x
    cell_y = tf.range(0, grid_n, dtype=tf.float32)
    cell_y = tf.tile(tf.expand_dims(cell_y, axis=0), [grid_n, 1])
    cell_y = tf.transpose(cell_y)
    cell_y = cell_y
    grid = tf.stack([cell_x, cell_y], axis=2)  # shape [grid_n, grid_n, 2]
    return grid

def size_and_move_grid(grid, cell_w, origin):
    return grid * cell_w + origin

def cxyw_rois(rois):
    rois_x1, rois_y1, rois_x2, rois_y2 = tf.unstack(rois, axis=1)  # rois shape [n, 4]
    # center coordinates of the roi
    rois_x = (rois_x1 + rois_x2) / 2.0
    rois_y = (rois_y1 + rois_y2) / 2.0
    rois_w = (rois_x2 - rois_x1)
    rois = tf.stack([rois_x, rois_y, rois_w], axis=1) # rois shape [rois_n, 3]
    return rois

def reshape_rois(rois, grid_n):
    cross_rois = tf.expand_dims(tf.expand_dims(rois, axis=0), axis=0)
    cross_rois = tf.tile(cross_rois, [grid_n, grid_n, 1, 1]) # shape [grid_n, grid_n, rois_n, 3]]
    return cross_rois

# returns set of booleans stating if ROI is centered in grid cell
# grid cells coordinates x,y represent top left corner of cell (not center)
# if expand>1.0, expands cells before applying condition
def center_in_grid_cell(grid, grid_n, cell_w, rois, expand=1.0):
    cross_rois = reshape_rois(rois, grid_n) # shape [grid_n, grid_n, rois_n, 3]]
    cross_rois_cx, cross_rois_cy, cross_rois_w = tf.unstack(cross_rois, axis=-1)
    grid_x, grid_y = tf.unstack(grid, axis=-1)
    has_center_x = tf.logical_and(tf.greater_equal(cross_rois_cx, tf.expand_dims(grid_x-(expand-1.0)*cell_w, -1)),  # broadcast !
                                  tf.less(cross_rois_cx, tf.expand_dims(grid_x+expand*cell_w, -1)))    # broadcast ! and broadcast !
    has_center_y = tf.logical_and(tf.greater_equal(cross_rois_cy, tf.expand_dims(grid_y-(expand-1)*cell_w, -1)),  # broadcast !
                                  tf.less(cross_rois_cy, tf.expand_dims(grid_y+expand*cell_w, -1)))    # broadcast ! and broadcast !
    has_center = tf.logical_and(has_center_x, has_center_y) # shape [grid_n, grid_n, rois_n]
    return has_center

# returns set of booleans stating if ROI is centered in grid cell periphery
# expand must be > 1.0 for this function to return positive results
# True for rois centered in expanded cell but not in non-expanded cell.
def center_in_grid_cell_periphery(grid, grid_n, cell_w, rois, expand=1.0):
    has_center = center_in_grid_cell(grid, grid_n, cell_w, rois, expand=1.0)
    has_center_expanded = center_in_grid_cell(grid, grid_n, cell_w, rois, expand=expand)
    has_center_peri = tf.logical_and(has_center_expanded, tf.logical_not(has_center))
    return has_center_peri

def gen_grid_for_tile(tile, grid_n):
    tile_x1, tile_y1, tile_x2, tile_y2 = tf.unstack(tile, axis=0)  # tile shape [4]
    cell_w = (tile_x2 - tile_x1) / grid_n
    grid = gen_grid(grid_n)
    grid = size_and_move_grid(grid, cell_w, [tile_x1, tile_y1])
    return grid, cell_w


# Splits the tile into grid_n x grid_n cells.
# For each cell, computes the n largest rois that are centered in the cell.
# Returns them ordered by decreasing size. Output shape [grid_n, grid_n, n, 3]
# (For now also converts rectangular ROIs to square ones.)
# If no roi centered in a cell, returns empty roi (0,0,0) for that cell.
# Supports alternative comparison types:
# comparator="largest_w": largest roi by width
# comparator="furthest_from_center": roi furthest from cell center
# comparator="closest_to_center": roi closest to cell center
def n_largest_rois_in_cell(tile, rois, rois_n, grid_n, n, comparator="largest_w", expand=1.0):
    grid, cell_w = gen_grid_for_tile(tile, grid_n)

    # grid shape [grid_n, grid_n, 2]
    # rois shape [rois_n, 3]

    rois = cxyw_rois(rois)
    cross_rois = reshape_rois(rois, grid_n)  # shape [grid_n, grid_n, rois_n, 3]]
    cross_rois_cx, cross_rois_cy, cross_rois_w = tf.unstack(cross_rois, axis=-1) # shape [grid_n, grid_n, rois_n]]
    has_center = center_in_grid_cell(grid, grid_n, cell_w, rois, expand=expand)

    grid_centers = (grid + grid + cell_w) / 2.0  # shape [grid_n, grid_n, 2]
    g_cx, g_cy = tf.unstack(grid_centers, axis=-1)  # shape [grid_n, grid_n]
    g_cx = tf.expand_dims(g_cx, axis=-1) # force broadcasting on correct axis
    g_cy = tf.expand_dims(g_cy, axis=-1)

    # iterate on largest a fixed number of times to get N largest
    n_largest = []
    zeros = tf.zeros(shape=[grid_n, grid_n, 3])
    for i in range(n):
        any_roi_in_cell = tf.reduce_any(has_center, axis=2) # shape [grid_n, grid_n]
        if comparator=="largest_w":
            largest_indices = tf.argmax(tf.cast(has_center, tf.float32) * cross_rois_w, axis=2)  # shape [grid_n, grid_n]
        elif comparator=="furthest_from_center":
            d_from_cell_center = tf.abs(cross_rois_cx - g_cx) + tf.abs(cross_rois_cy - g_cy)
            largest_indices = tf.argmax(tf.cast(has_center, tf.float32) * d_from_cell_center, axis=2)  # shape [grid_n, grid_n]
        elif comparator=="closest_to_center":
            d_from_cell_center = tf.abs(cross_rois_cx - g_cx) + tf.abs(cross_rois_cy - g_cy)
            ones = tf.ones(tf.shape(d_from_cell_center))
            largest_indices = tf.argmin(tf.where(has_center, d_from_cell_center, 1000*ones), axis=2)  # shape [grid_n, grid_n]
        # as of TF1.3 can use tf.gather(axis=2)
        rs_largest_indices = tf.reshape(largest_indices, [grid_n*grid_n])
        rs_largest_indices = tf.unstack(rs_largest_indices, axis=0)  # list
        rs_cross_rois = tf.reshape(cross_rois, [grid_n*grid_n, rois_n, 3])
        rs_cross_rois = tf.unstack(rs_cross_rois, axis=0) # list
        rs_largest_roi_in_cell = [tf.gather(cr, li) for cr, li in zip(rs_cross_rois, rs_largest_indices)]
        largest_roi_in_cell = tf.stack(rs_largest_roi_in_cell, axis=0)  # shape [grid_n * grid_n, 3]
        largest_roi_in_cell = tf.reshape(largest_roi_in_cell, [grid_n, grid_n, 3]) # shape [grid_n, grid_n, 3]
        # cells that do not have a roi in them, set their "largest roi in cell" to (x=0,y=0,w=0)
        any_roi_in_cell = tf.tile(tf.expand_dims(any_roi_in_cell, axis=-1), [1, 1, 3])  # shape [grid_n, grid_n, 3]
        largest_roi_in_cell = tf.where(any_roi_in_cell, largest_roi_in_cell, zeros) # shape [grid_n, grid_n, 3]
        n_largest.append(largest_roi_in_cell)
        # zero-out the largest element per cell to get the next largest on the next iteration
        zero_mask = tf.logical_not(tf.cast(tf.one_hot(largest_indices, rois_n), dtype=tf.bool))
        has_center = tf.logical_and(has_center, zero_mask)
    n_largest = tf.stack(n_largest, axis=2)  # shape [grid_n, grid_n, n, 3]
    return n_largest # shape [grid_n, grid_n, n, 3]

def make_rois_tile_cell_relative(tile, tiled_rois, grid_n):
    grid, cell_w = gen_grid_for_tile(tile, grid_n)
    tile_w = cell_w * grid_n

    # tiled_rois shape [grid_n, grid_n, n, 3] n = CELL_B

    # compute grid cell centers
    grid_centers = (grid + grid + cell_w) / 2.0  # shape [grid_n, grid_n, 2]

    gc_x, gc_y = tf.unstack(grid_centers, axis=-1)  # shape [grid_n, grid_n]
    # force broadcasting on correct axis
    gc_x = tf.expand_dims(gc_x, axis=-1)
    gc_y = tf.expand_dims(gc_y, axis=-1)
    tr_x, tr_y, tr_w = tf.unstack(tiled_rois, axis=-1) # shape [grid_n, grid_n, n] n = CELL_B

    ctr_x = (tr_x - gc_x) / (cell_w/2.0)  # constrain x within [-1, 1] in cell center relative coordinates
    ctr_y = (tr_y - gc_y) / (cell_w/2.0)  # constrain y within [-1, 1] in cell center relative coordinates
    ctr_w = tr_w / tile_w  # constrain w within [0, 1] in tile-relative coordinates

    # leave x, y coordinates unchanged (as 0) if the width is zero (empty box)
    ctr_x = tf.where(tf.greater(tr_w, 0), ctr_x, tr_x)
    ctr_y = tf.where(tf.greater(tr_w, 0), ctr_y, tr_x)

    rois = tf.stack([ctr_x, ctr_y, ctr_w], axis=-1)
    return rois


def n_largest_rois_in_cell_relative(tile, rois, rois_n, grid_n, n, comparator="largest_w", expand=1.0):
    rois = n_largest_rois_in_cell(tile, rois, rois_n, grid_n, n, comparator=comparator, expand=expand)
    rois = make_rois_tile_cell_relative(tile, rois, grid_n)
    return rois


def n_experimental_roi_selection_strategy(tile, rois, rois_n, grid_n, n):
    assert n == 2  # only implemented for CELL_B=2
    normal_rois = n_largest_rois_in_cell_relative(tile, rois, rois_n, grid_n, n, comparator="closest_to_center", expand=1.0)
    periph_rois = n_largest_rois_in_cell_relative(tile, rois, rois_n, grid_n, n, comparator="closest_to_center", expand=1.3)

    # TODO: count number of non-zero rois in both, then use decision table
    # normal_rois   periph_rois   result
    #    0     0      0     0      0    0   (a0)
    #    x     0      0     0      x    x   (a0)
    #    x     y      0     0      x    y   (a1)
    #    0     0      z     0      z    z   (a2)
    #    0     0      z     t      z    t   (a3)
    #    x     0      z     0      x    z   (a4)
    #    x     y      z     0      x    y   (a1)
    #    x     0      z     t      x    z   (a4)
    #    x     y      z     t      x    y   (a1)

    def roi_select(rois):
        r1, r2, p1, p2 = tf.unstack(rois, axis=0)  # result shape [3]
        a0 = tf.stack([r1, r1])
        a1 = tf.stack([r1, r2])
        a2 = tf.stack([p1, p1])
        a3 = tf.stack([p1, p2])
        a4 = tf.stack([r1, p1])
        a5 = tf.stack([p2, p2])
        a6 = tf.stack([r1, p2])
        a7 = tf.stack([r2, r2])
        a8 = tf.stack([r2, p2])
        a9 = tf.stack([r2, p1])
        _, _, w = tf.unstack(rois, axis=1)  # result shape [4]
        nz = tf.greater(w, 0)
        zero = tf.zeros(tf.shape(a0))
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, False, False, False])), a0, zero)
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, False, False, True])), a5, r)  # cannot happen
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, False, True, False])), a2, r)
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, False, True, True])), a3, r)
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, True, False, False])), a7, r)  # cannot happen
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, True, False, True])), a8, r)  # cannot happen
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, True, True, False])), a9, r)  # cannot happen
        r = tf.where(tf.reduce_all(tf.equal(nz, [False, True, True, True])), a9, r)  # cannot happen
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, False, False, False])), a0, r)
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, False, False, True])), a6, r)  # yes, can happen
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, False, True, False])), a4, r)
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, False, True, True])), a4, r)
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, True, False, False])), a1, r)
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, True, False, True])), a1, r)  # cannot happen
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, True, True, False])), a1, r)
        r = tf.where(tf.reduce_all(tf.equal(nz, [True, True, True, True])), a1, r)
        return r

    rsnormal_rois = tf.reshape(normal_rois, [grid_n * grid_n, n, 3])
    rx, ry, rw = tf.unstack(rsnormal_rois, axis=-1)
    rsperiph_rois = tf.reshape(periph_rois, [grid_n * grid_n, n, 3])
    px, py, pw = tf.unstack(rsperiph_rois, axis=-1)
    roi_exclude = tf.equal(rw, pw)
    zero = tf.zeros_like(pw)
    pw = tf.where(roi_exclude, zero, pw)  # keep in periphery rois only rois that are NOT in normal rois, i.e. rois further than 1 cell radius
    rsperiph_rois = tf.stack([px, py, pw], axis=2)
    rscombined_rois = tf.concat([rsnormal_rois, rsperiph_rois], axis=1)
    rscombined_rois = tf.map_fn(roi_select, rscombined_rois)
    combined_rois = tf.reshape(rscombined_rois, [grid_n, grid_n, n, 3])
    return combined_rois


def grid_cell_to_tile_coords(rois, grid_n, tile_size):
    # converts between coordinates used internally by the model
    # and coordinates expected by Tensorflow's draw_bounding_boxes function
    #
    # input coords:
    # shape [batch, grid_n, grid_n, n, 3]
    # coordinates in last dimension are x, y, w
    # x and y are in [-1, 1] relative to grid cell center and size of grid cell
    # w is in [0, 1] relatively to tile size. w is a "diameter", not "radius"
    #
    # output coords:
    # shape [batch, grid_n, grid_n, n, 4]
    # coordinates in last dimension are y1, x1, y2, x2
    # relatively to tile_size

    # grid for (0,0) based tile of size tile_size
    cell_w = tile_size/grid_n
    grid = gen_grid(grid_n) * cell_w
    # grid cell centers
    grid_centers = (grid + grid + cell_w) / 2.0  # shape [grid_n, grid_n, 2]
    # roi coordinates
    roi_cx, roi_cy, roi_w = tf.unstack(rois, axis=-1) # shape [batch, grid_n, grid_n, n]
    # grid centers unstacked
    gr_cx, gr_cy = tf.unstack(grid_centers, axis=-1) # shape [grid_n, grid_n]
    gr_cx = tf.expand_dims(tf.expand_dims(gr_cx, 0), 3) # shape [1, grid_n, grid_n, 1]
    gr_cy = tf.expand_dims(tf.expand_dims(gr_cy, 0), 3) # shape [1, grid_n, grid_n, 1]
    roi_cx = roi_cx * cell_w/2 # roi_x=1 means cell center + cell_w/2
    roi_cx = roi_cx+gr_cx
    roi_cy = roi_cy * cell_w/2 # roi_x=1 means cell center + cell_w/2
    roi_cy = roi_cy+gr_cy
    roi_w = roi_w * tile_size
    roi_x1 = roi_cx - roi_w/2
    roi_x2 = roi_cx + roi_w/2
    roi_y1 = roi_cy - roi_w/2
    roi_y2 = roi_cy + roi_w/2
    rois = tf.stack([roi_y1, roi_x1, roi_y2, roi_x2], axis=4)  # shape [batch, grid_n, grid_n, n, 4]
    return rois











