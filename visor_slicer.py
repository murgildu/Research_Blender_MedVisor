import bpy
import numpy as np
import gpu
from gpu_extras.batch import batch_for_shader

_volumen_global = None
_loncha_actual  = None
_plano_actual   = None
_draw_handle    = None

def guardar_volumen(volumen_np: np.ndarray):
    """Guarda el array NIfTI en la memoria RAM del Addon"""
    global _volumen_global
    _volumen_global = volumen_np.astype(np.float32)
    print(f"[MedVision] Volumen guardado en memoria. Shape: {_volumen_global.shape}")

def _normalizar(loncha: np.ndarray) -> np.ndarray:
    loncha = np.flipud(loncha).astype(np.float32)
    vmin, vmax = loncha.min(), loncha.max()
    if vmax > vmin:
        return (loncha - vmin) / (vmax - vmin)
    return np.zeros_like(loncha)

def _dibujar_slice():
    global _loncha_actual, _plano_actual
    if _loncha_actual is None: return

    ctx = bpy.context
    if not ctx.area or ctx.area.type != 'VIEW_3D': return
    rv3d = ctx.region_data
    if not rv3d: return

    import math
    vista_ok = False
    if rv3d.view_perspective == 'PERSP':
        vista_ok = True
    elif rv3d.view_perspective == 'ORTHO':
        rot = rv3d.view_rotation.to_euler()
        rx_abs, rz_abs = abs(round(math.degrees(rot.x))), abs(round(math.degrees(rot.z)))
        if _plano_actual == 'AXIAL' and (rx_abs == 0 or rx_abs == 180): vista_ok = True
        elif _plano_actual == 'CORONAL' and rx_abs == 90 and (rz_abs == 0 or rz_abs == 180): vista_ok = True
        elif _plano_actual == 'SAGITAL' and rx_abs == 90 and (rz_abs == 90 or rz_abs == 270): vista_ok = True

    if not vista_ok: return

    region = ctx.region
    rw, rh = region.width, region.height
    h_img, w_img = _loncha_actual.shape

    ratio = w_img / h_img if h_img > 0 else 1.0
    if rw / rh > ratio:
        ph, pw = rh, int(rh * ratio)
    else:
        pw, ph = rw, int(rw / ratio)
    
    x0, y0 = (rw - pw) // 2, (rh - ph) // 2
    x1, y1 = x0 + pw, y0 + ph

    datos = _loncha_actual
    h, w = datos.shape
    rgba = np.stack([datos, datos, datos, np.ones_like(datos)], axis=-1)
    buf = gpu.types.Buffer('FLOAT', [h * w * 4], rgba.flatten())
    tex = gpu.types.GPUTexture((w, h), format='RGBA32F', data=buf)

    shader = gpu.shader.from_builtin('IMAGE')
    batch = batch_for_shader(
        shader, 'TRIS',
        {"pos": ((x0,y0),(x1,y0),(x1,y1),(x0,y1)), "texCoord": ((0,0), (1,0), (1,1), (0,1))},
        indices=((0,1,2),(0,2,3))
    )

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_sampler("image", tex)
    batch.draw(shader)
    gpu.state.blend_set('NONE')

def _registrar_handler():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_dibujar_slice, (), 'WINDOW', 'POST_PIXEL')

def _eliminar_handler():
    global _draw_handle
    if _draw_handle is not None:
        try: bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        except: pass
        _draw_handle = None

def actualizar_corte(self, context):
    global _volumen_global, _loncha_actual, _plano_actual
    if _volumen_global is None: return

    volumen_np = _volumen_global
    plano = context.scene.corte_plano
    profundidad = context.scene.corte_profundidad

    if plano == 'AXIAL': max_limite = volumen_np.shape[0] - 1
    elif plano == 'CORONAL': max_limite = volumen_np.shape[1] - 1
    elif plano == 'SAGITAL': max_limite = volumen_np.shape[2] - 1
    else: return

    if profundidad > max_limite:
        context.scene.corte_profundidad = max_limite
        profundidad = max_limite

    try:
        if plano == 'AXIAL': loncha = volumen_np[profundidad, :, :]
        elif plano == 'CORONAL': loncha = volumen_np[:, profundidad, :]
        elif plano == 'SAGITAL': loncha = volumen_np[:, :, profundidad]
    except IndexError: return

    _loncha_actual = _normalizar(loncha)
    _plano_actual = plano
    _registrar_handler()

    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def unregister():
    global _volumen_global, _loncha_actual, _plano_actual
    _eliminar_handler()
    _volumen_global = None
    _loncha_actual = None
    _plano_actual = None