import bpy
import numpy as np
import gpu
from gpu_extras.batch import batch_for_shader

class EstadoVisor:
    #Clase para meter todo el estado en memoria del visor 
    def __init__(self):
        self.volumen = None
        self.volumen_pve = {}
        
        self.lonchas = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
        self.lonchas_pve = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
        self.texturas = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
        self.texturas_pve = {'AXIAL': None, 'CORONAL': None, 'SAGITAL': None}
        
        self.draw_handle = None
        self.crosshair_active = False
        self.img_rect = {
            'AXIAL': {'x0': 0, 'y0': 0, 'pw': 1, 'ph': 1},
            'CORONAL': {'x0': 0, 'y0': 0, 'pw': 1, 'ph': 1},
            'SAGITAL': {'x0': 0, 'y0': 0, 'pw': 1, 'ph': 1}
        }

    def limpiar(self):
        """Libera la memoria de todos los arrays y texturas."""
        if self.draw_handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, 'WINDOW')
            except ValueError:
                pass # Capturamos el error específico en lugar de un Exception genérico
            self.draw_handle = None
            
        self.volumen = None
        self.volumen_pve = {}
        self.lonchas = {k: None for k in self.lonchas}
        self.lonchas_pve = {k: None for k in self.lonchas_pve}
        self.texturas = {k: None for k in self.texturas}
        self.texturas_pve = {k: None for k in self.texturas_pve}

estado = EstadoVisor()

def actualizar_tejido(self, context):
    """Fuerza la recarga de las 3 texturas al cambiar el menú de FSL"""
    if estado.volumen is not None:
        _actualizar_corte_generico(context, 'AXIAL', context.scene.corte_axial)
        _actualizar_corte_generico(context, 'CORONAL', context.scene.corte_coronal)
        _actualizar_corte_generico(context, 'SAGITAL', context.scene.corte_sagital)

def _detectar_vista(rv3d):
    if rv3d is None:
        return None

    vista = getattr(rv3d, 'view', None)

    if vista in ('TOP', 'BOTTOM'):
        return 'AXIAL'
    if vista in ('FRONT', 'BACK'):
        return 'CORONAL'
    if vista in ('RIGHT', 'LEFT'):
        return 'SAGITAL'

    if rv3d.view_perspective == 'ORTHO':
        import math
        rot  = rv3d.view_rotation.to_euler()
        rx   = abs(round(math.degrees(rot.x)))
        rz   = abs(round(math.degrees(rot.z)))
        if rx in (0, 180):
            return 'AXIAL'
        if rx == 90 and rz in (0, 180):
            return 'CORONAL'
        if rx == 90 and rz in (90, 270):
            return 'SAGITAL'

    return None

def _transformar_loncha(plano: str, loncha: np.ndarray) -> np.ndarray:
    if plano == 'AXIAL':
        return np.flipud(loncha)
    if plano == 'CORONAL':
        return np.flipud(np.rot90(loncha, k=2))
    if plano == 'SAGITAL':
        return np.fliplr(np.rot90(loncha.T, k=3))
    return loncha

def _actualizar_textura(plano: str, loncha_mri: np.ndarray, loncha_pve: np.ndarray = None, tejido: str = 'NONE'):

     # 1. TEXTURA MRI BASE
    vmin, vmax = loncha_mri.min(), loncha_mri.max()
    datos = ((loncha_mri - vmin) / (vmax - vmin)).astype(np.float32) if vmax > vmin else np.zeros_like(loncha_mri, dtype=np.float32)
    h, w = datos.shape
    
    # MÁSCARA AISLANTE
    if tejido.startswith('SOLO_') and loncha_pve is not None:
        alfa_mri = (loncha_pve > 0.50).astype(np.float32)
    else:
        alfa_mri = (datos > 0.02).astype(np.float32)
 
    rgba_mri = np.stack([datos, datos, datos, alfa_mri], axis=-1)
    buf_mri = gpu.types.Buffer('FLOAT', h * w * 4, rgba_mri.flatten().tolist())
    
    estado.texturas[plano] = gpu.types.GPUTexture((w, h), format='RGBA32F', data=buf_mri)

    # 2. TEXTURA PVE
    if loncha_pve is not None and tejido.startswith('PVE_'):
        r = np.ones_like(loncha_pve, dtype=np.float32)
        g = np.ones_like(loncha_pve, dtype=np.float32)
        b = np.ones_like(loncha_pve, dtype=np.float32)
        
        if tejido == 'PVE_1':   
            r *= 0.2; g *= 0.9; b *= 0.2
        elif tejido == 'PVE_2': 
            r *= 0.9; g *= 0.4; b *= 0.1
        elif tejido == 'PVE_0': 
            r *= 0.1; g *= 0.4; b *= 0.9

        alfa_pve = np.clip(loncha_pve, 0.0, 1.0).astype(np.float32)
        rgba_pve = np.stack([r, g, b, alfa_pve], axis=-1)
        buf_pve = gpu.types.Buffer('FLOAT', h * w * 4, rgba_pve.flatten().tolist())
        
        estado.texturas_pve[plano] = gpu.types.GPUTexture((w, h), format='RGBA32F', data=buf_pve)
    else:
        estado.texturas_pve[plano] = None

def guardar_volumen(volumen_np: np.ndarray, volumenes_pve_dict: dict = None):
    estado.volumen = volumen_np.astype(np.float32)
    
    if volumenes_pve_dict:
        estado.volumen_pve = {k: v.astype(np.float32) for k, v in volumenes_pve_dict.items()}
    else:
        estado.volumen_pve = {}

    tejido = bpy.context.scene.tejido_visualizado
    clave_diccionario = tejido.replace('SOLO_', 'PVE_')
    
    z_mid = estado.volumen.shape[0] // 2
    y_mid = estado.volumen.shape[1] // 2
    x_mid = estado.volumen.shape[2] // 2

    for plano, raw_mri in (
        ('AXIAL',   estado.volumen[z_mid, :, :]),
        ('CORONAL', estado.volumen[:, y_mid, :]),
        ('SAGITAL', estado.volumen[:, :, x_mid]),
    ):
        loncha_mri = _transformar_loncha(plano, raw_mri)
        estado.lonchas[plano] = loncha_mri
        
        loncha_pve = None
        if estado.volumen_pve and clave_diccionario in estado.volumen_pve and clave_diccionario != 'NONE':
            matriz_tejido = estado.volumen_pve[clave_diccionario]
            if plano == 'AXIAL': raw_pve = matriz_tejido[z_mid, :, :]
            elif plano == 'CORONAL': raw_pve = matriz_tejido[:, y_mid, :]
            elif plano == 'SAGITAL': raw_pve = matriz_tejido[:, :, x_mid]
            
            loncha_pve = _transformar_loncha(plano, raw_pve)
            estado.lonchas_pve[plano] = loncha_pve

        _actualizar_textura(plano, loncha_mri, loncha_pve, tejido)

    activar_visor()

def _actualizar_corte_generico(context, plano, profundidad):
    if estado.volumen is None: return

    volumen_np = estado.volumen
    tejido = context.scene.tejido_visualizado
    
    clave_diccionario = tejido.replace('SOLO_', 'PVE_')
    
    limites = {
        'AXIAL':   volumen_np.shape[0] - 1,
        'CORONAL': volumen_np.shape[1] - 1,
        'SAGITAL': volumen_np.shape[2] - 1,
    }
    max_limite = limites.get(plano, 0)
    profundidad = min(profundidad, max_limite)

    try:
        raw_pve = None
        if plano == 'AXIAL':
            raw_mri = volumen_np[profundidad, :, :]
            if estado.volumen_pve and clave_diccionario in estado.volumen_pve and clave_diccionario != 'NONE':
                raw_pve = estado.volumen_pve[clave_diccionario][profundidad, :, :]
        elif plano == 'CORONAL':
            raw_mri = volumen_np[:, profundidad, :]
            if estado.volumen_pve and clave_diccionario in estado.volumen_pve and clave_diccionario != 'NONE':
                raw_pve = estado.volumen_pve[clave_diccionario][:, profundidad, :]
        elif plano == 'SAGITAL':
            raw_mri = volumen_np[:, :, profundidad]
            if estado.volumen_pve and clave_diccionario in estado.volumen_pve and clave_diccionario != 'NONE':
                raw_pve = estado.volumen_pve[clave_diccionario][:, :, profundidad]
        else: return
    except IndexError: return

    loncha_mri = _transformar_loncha(plano, raw_mri)
    estado.lonchas[plano] = loncha_mri
    
    loncha_pve = _transformar_loncha(plano, raw_pve) if raw_pve is not None else None
    estado.lonchas_pve[plano] = loncha_pve

    _actualizar_textura(plano, loncha_mri, loncha_pve, tejido)

    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def forzar_redibujado(self, context):
    """Refresca la pantalla inmediatamente al mover el slider de zoom"""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def actualizar_corte_axial(self, context):
    _actualizar_corte_generico(context, 'AXIAL', self.corte_axial)

def actualizar_corte_coronal(self, context):
    _actualizar_corte_generico(context, 'CORONAL', self.corte_coronal)

def actualizar_corte_sagital(self, context):
    _actualizar_corte_generico(context, 'SAGITAL', self.corte_sagital)

def activar_visor():
    """Registra el draw handler y re-registra el HUD de texto encima."""
    if estado.draw_handle is None:
        estado.draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _dibujar_slice, (), 'WINDOW', 'POST_PIXEL'
        )

    if "hud_medico_handle" in bpy.app.driver_namespace:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                bpy.app.driver_namespace["hud_medico_handle"], 'WINDOW'
            )
        except Exception:
            pass
        from . import paneles_ui
        nuevo_handle = bpy.types.SpaceView3D.draw_handler_add(
            paneles_ui.dibujar_nombres_medicos, (), 'WINDOW', 'POST_PIXEL'
        )
        bpy.app.driver_namespace["hud_medico_handle"] = nuevo_handle


def _dibujar_slice():
    ctx = bpy.context
    if not ctx.area or ctx.area.type != 'VIEW_3D':
        return
    rv3d = ctx.region_data
    if not rv3d:
        return

    view_type = _detectar_vista(rv3d)
    if view_type is None:
        return

    region = ctx.region
    rw, rh = region.width, region.height

    # 1. Fondo opaco
    try:
        tema_bg = ctx.preferences.themes[0].view_3d.space.gradients.high_gradient
        color_fondo = (tema_bg[0], tema_bg[1], tema_bg[2], 1.0)
    except AttributeError:
        color_fondo = (0.11, 0.11, 0.11, 1.0)

    verts_bg   = ((0, 0), (rw, 0), (rw, rh), (0, rh))
    indices_bg = ((0, 1, 2), (0, 2, 3))

    try:
        shader_bg = gpu.shader.from_builtin('UNIFORM_COLOR')
    except Exception:
        shader_bg = gpu.shader.from_builtin('2D_UNIFORM_COLOR')

    batch_bg = batch_for_shader(shader_bg, 'TRIS', {"pos": verts_bg}, indices=indices_bg)
    shader_bg.bind()
    shader_bg.uniform_float("color", color_fondo)
    batch_bg.draw(shader_bg)

    # 2. Imagen 2D
    tex    = estado.texturas[view_type]
    loncha = estado.lonchas[view_type]
    if tex is None or loncha is None:
        return

    h_img, w_img = loncha.shape

    h_img, w_img = loncha.shape
    ratio = w_img / h_img if h_img > 0 else 1.0
    if rw / rh > ratio:
        ph, pw = rh, int(rh * ratio)
    else:
        pw, ph = rw, int(rw / ratio)

    zoom_factor = 1.0
    offset_x = 0.0
    offset_y = 0.0
    
    if view_type == 'AXIAL':
        zoom_factor = ctx.scene.zoom_axial
        offset_x = ctx.scene.offset_x_axial
        offset_y = ctx.scene.offset_y_axial
    elif view_type == 'CORONAL':
        zoom_factor = ctx.scene.zoom_coronal
        offset_x = ctx.scene.offset_x_coronal
        offset_y = ctx.scene.offset_y_coronal
    elif view_type == 'SAGITAL':
        zoom_factor = ctx.scene.zoom_sagital
        offset_x = ctx.scene.offset_x_sagital
        offset_y = ctx.scene.offset_y_sagital

    pw = int(pw * zoom_factor)
    ph = int(ph * zoom_factor)

    # Sumamos el offset matemático para mover la imagen
    x0 = (rw - pw) // 2 + int(offset_x)
    y0 = (rh - ph) // 2 + int(offset_y)
    x1 = x0 + pw
    y1 = y0 + ph

    estado.img_rect[view_type] = {'x0': x0, 'y0': y0, 'pw': pw, 'ph': ph}

    try:
        shader_img = gpu.shader.from_builtin('IMAGE')
    except Exception:
        shader_img = gpu.shader.from_builtin('2D_IMAGE')

    batch_img = batch_for_shader(
        shader_img, 'TRIS',
        {
            "pos":      ((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
            "texCoord": ((0, 0),   (1, 0),   (1, 1),   (0, 1)),
        },
        indices=((0, 1, 2), (0, 2, 3)),
    )

    gpu.state.blend_set('ALPHA')
    
    # --- PASADA 1: Dibujar Resonancia Magnética ---
    shader_img.bind()
    shader_img.uniform_sampler("image", tex)
    batch_img.draw(shader_img)
    
    # --- PASADA 2: Dibujar Segmentación (PVE) por encima ---
    tex_pve = estado.texturas_pve[view_type]
    if tex_pve is not None:
        shader_img.uniform_sampler("image", tex_pve)
        batch_img.draw(shader_img)

    gpu.state.blend_set('NONE')

    if estado.crosshair_active:
        vol_shape = ctx.scene.get("medvisor_volumen_shape", [256, 256, 256])
        
        c_ax = ctx.scene.corte_axial
        c_cor = ctx.scene.corte_coronal
        c_sag = ctx.scene.corte_sagital
        
        max_z = max(1, vol_shape[0] - 1)
        max_y = max(1, vol_shape[1] - 1)
        max_x = max(1, vol_shape[2] - 1)
        
        # 3. Convertimos los cortes a porcentajes relativos (0.0 a 1.0)
        rz = c_ax / max_z
        ry = c_cor / max_y
        rx = c_sag / max_x
        
        # 4. Asignamos qué porcentaje usa cada vista (SIMETRÍA EXACTA CON EL CLIC)
        if view_type == 'AXIAL':
            cx, cy = rx, 1.0 - ry      
        elif view_type == 'CORONAL':
            cx, cy = rx, 1.0 - rz      
        elif view_type == 'SAGITAL':
            cx, cy = ry, 1.0 - rz      
        else:
            cx, cy = 0.5, 0.5

        # 5. Calculamos los píxeles en pantalla
        line_x = x0 + (cx * pw)
        line_y = y0 + (cy * ph)
        
        verts_line = (
            (x0, line_y), (x1, line_y), # Línea Horizontal
            (line_x, y0), (line_x, y1)  # Línea Vertical
        )
        indices_line = ((0, 1), (2, 3))
        
        try:
            shader_line = gpu.shader.from_builtin('UNIFORM_COLOR')
        except:
            shader_line = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
            
        batch_line = batch_for_shader(shader_line, 'LINES', {"pos": verts_line}, indices=indices_line)
        
        shader_line.bind()
        shader_line.uniform_float("color", (1.0, 0.0, 0.0, 0.8)) # Rojo
        batch_line.draw(shader_line)

def unregister():
    estado.limpiar()