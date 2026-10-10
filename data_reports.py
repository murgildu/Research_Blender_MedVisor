import os
import json
import base64
from datetime import datetime

def cargar_o_crear_informe(ruta_informe: str) -> dict:
    if os.path.exists(ruta_informe):
        with open(ruta_informe, 'r', encoding='utf-8') as f:
            informe = json.load(f)
        informe["metadata"]["fecha_ultimo_registro"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return informe

    return {
        "metadata": {
            "fecha_creacion_bd": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "herramientas": "HD-BET + FSL FAST + SIENAX + SIENA (WSL)",
        },
        "pacientes": {},
    }

def _paciente(informe: dict, sujeto: str) -> dict:
    entrada = informe["pacientes"].setdefault(sujeto, {})
    entrada.setdefault("sesiones", {})
    entrada.setdefault("comparaciones_longitudinales", {})
    return entrada

def fusionar_resultado(informe: dict, resultado: dict):
    entrada = _paciente(informe, resultado["paciente"])

    if resultado["tipo"] == "transversal":
        entrada["sesiones"][resultado["sesion"]] = {
            "fecha_adquisicion": resultado["fecha"],
            "archivo_original": resultado["archivo_original"],
            "volumenes_absolutos_mm3": resultado["volumenes_absolutos_mm3"],
            "volumenes_sienax_normalizados": resultado.get("volumenes_sienax_normalizados", {}),
            "z_scores_adni": resultado.get("z_scores", {}),
            "anomalias_detectadas": resultado.get("anomalias_zscore_detectadas", 0)
        }
    else: 
        clave = f"{resultado['sesion_basal']}_vs_{resultado['sesion_seguimiento']}"
        entrada["comparaciones_longitudinales"][clave] = {
            "archivo_basal": resultado["archivo_basal"],
            "archivo_seguimiento": resultado["archivo_seguimiento"],
            "pbvc_porcentaje": resultado["metricas"].get("pbvc_porcentaje"),
        }

def guardar_json(informe: dict, ruta_salida: str):
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=4, ensure_ascii=False)

def _imagen_a_base64(ruta_imagen: str) -> str:
    if not ruta_imagen or not os.path.exists(ruta_imagen):
        return ""
    with open(ruta_imagen, "rb") as f:
        datos = base64.b64encode(f.read()).decode("utf-8")
    extension = os.path.splitext(ruta_imagen)[1].lstrip('.').lower() or "png"
    return f"data:image/{extension};base64,{datos}"

def generar_html(resultados, ruta_informe_html):
    html_content = f"""<!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Reporte Clínico MedVision</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            h2 {{ color: #2980b9; margin-top: 30px; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
            .header-info {{ background: #ecf0f1; padding: 15px; border-radius: 6px; margin-bottom: 20px; display: flex; justify-content: space-between; flex-wrap: wrap; border-left: 5px solid #3498db; }}
            .header-info div {{ margin: 5px 15px 5px 0; }}
            .header-info p {{ margin: 5px 0; font-weight: bold; }}
            .header-info span {{ font-weight: normal; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 30px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #34495e; color: white; }}
            tr:hover {{ background-color: #f5f5f5; }}
            
            /* Estilos para alertas Z-Score */
            .alert-z {{ color: #c0392b; font-weight: bold; background-color: #fadbd8; padding: 3px 8px; border-radius: 4px; display: inline-block; border: 1px solid #e74c3c; }}
            .normal-z {{ color: #27ae60; font-weight: bold; }}
            .anomaly-warning {{ background-color: #fdf2e9; border-left: 5px solid #e67e22; padding: 10px 15px; margin-bottom: 20px; border-radius: 4px; }}
            
            .qa-section {{ margin-top: 40px; }}
            .qa-card {{ display: flex; flex-direction: column; background: #fafafa; border: 1px solid #e0e0e0; border-radius: 6px; margin-bottom: 25px; overflow: hidden; }}
            .qa-header {{ background: #2c3e50; color: white; padding: 10px 15px; margin: 0; font-size: 16px; }}
            .qa-body {{ padding: 15px; display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }}
            .qa-description {{ flex: 1; min-width: 250px; font-size: 14px; color: #555; line-height: 1.5; }}
            .qa-image {{ max-width: 65%; border-radius: 4px; border: 1px solid #ccc; }}
            .qa-image-full {{ max-width: 100%; border-radius: 4px; border: 1px solid #ccc; margin-top: 10px; }}
            .credits-section {{ margin-top: 40px; padding-top: 20px; border-top: 2px solid #ecf0f1; font-size: 12px; color: #7f8c8d; line-height: 1.6; }}
            .credits-section h3 {{ color: #34495e; font-size: 14px; margin-bottom: 10px; }}
            .references {{ padding-left: 15px; margin-bottom: 15px; }}
            .references li {{ margin-bottom: 6px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Informe Volumétrico MedVision</h1>
    """

    def formatear_zscore(valor):
        if valor is None or valor == "N/A":
            return "N/A"
        try:
            val_float = float(valor)
            if abs(val_float) > 2.0:
                return f'<span class="alert-z">{val_float:.2f} ⚠️</span>'
            else:
                return f'<span class="normal-z">{val_float:.2f}</span>'
        except:
            return "N/A"

    for res in resultados:
        paciente = res.get("paciente", "Desconocido")
        sesion = res.get("sesion", "Desconocida")
        tipo = res.get("tipo", "transversal")
        archivo_orig = res.get("archivo_original", "N/A")
        
        v_abs = res.get("volumenes_absolutos_mm3", {})
        v_norm = res.get("volumenes_sienax_normalizados", {})
        z_scores = res.get("z_scores", {})
        anomalias = res.get("anomalias_zscore_detectadas", 0)
        imgs = res.get("imagenes_fsl", {})

        html_content += f"""
            <div class="header-info">
                <div>
                    <p>Paciente: <span>{paciente}</span></p>
                    <p>Sesión: <span>{sesion}</span></p>
                </div>
                <div>
                    <p>Modalidad: <span>{tipo.capitalize()}</span></p>
                    <p>Archivo: <span>{archivo_orig}</span></p>
                </div>
                <div>
                    <p>Fecha Reporte: <span>{datetime.now().strftime('%Y-%m-%d %H:%M')}</span></p>
                </div>
            </div>
        """

        if anomalias > 0:
            html_content += f"""
            <div class="anomaly-warning">
                <strong>⚠️ Alerta Clínica:</strong> Se han detectado <strong>{anomalias}</strong> anomalías volumétricas (|Z-Score| > 2.0) en comparación con la cohorte sana de referencia (ADNI).
            </div>
            """

        html_content += f"""
            <h2>Cuantificación Tisular</h2>
            <table>
                <tr>
                    <th>Tejido Anatómico</th>
                    <th>Volumen Absoluto (mm³)</th>
                    <th>Volumen Normalizado (mm³) *</th>
                    <th>Z-Score (vs. Sanos ADNI) **</th>
                </tr>
                <tr>
                    <td>Materia Gris (GM)</td>
                    <td>{v_abs.get("materia_gris", "N/A")}</td>
                    <td>{v_norm.get("materia_gris_normalizada", "N/A") if v_norm else "N/A"}</td>
                    <td>{formatear_zscore(z_scores.get("z_score_materia_gris", "N/A"))}</td>
                </tr>
                <tr>
                    <td>Materia Blanca (WM)</td>
                    <td>{v_abs.get("materia_blanca", "N/A")}</td>
                    <td>{v_norm.get("materia_blanca_normalizada", "N/A") if v_norm else "N/A"}</td>
                    <td>{formatear_zscore(z_scores.get("z_score_materia_blanca", "N/A"))}</td>
                </tr>
                <tr>
                    <td>Líquido Cefalorraquídeo (CSF)</td>
                    <td>{v_abs.get("liquido_cefalorraquideo", "N/A")}</td>
                    <td>N/A</td>
                    <td>{formatear_zscore(z_scores.get("z_score_liquido_cefalorraquideo", "N/A"))}</td>
                </tr>
                <tr style="font-weight: bold; background-color: #e8f4f8;">
                    <td>Volumen Cerebral Total (TBV)</td>
                    <td>{v_abs.get("volumen_intracraneal_total", "N/A")}</td>
                    <td>{v_norm.get("volumen_cerebral_total_normalizado", "N/A") if v_norm else "N/A"}</td>
                    <td>{formatear_zscore(z_scores.get("z_score_volumen_intracraneal_total", "N/A"))}</td>
                </tr>
            </table>
        """
        
        if v_norm or z_scores:
            v_scale = v_norm.get("v_scale", "N/A") if v_norm else "N/A"
            html_content += f"""
            <p style="font-size: 12px; color: #7f8c8d; margin-top: -20px; margin-bottom: 30px;">
                * La normalización se estima multiplicando el volumen absoluto por el Factor de Escala de SIENAX (v_scale: {v_scale}).<br>
                ** Z-Score calculado usando la fórmula z = (x - μ) / σ frente a población de referencia sana. Valores > 2.0 o < -2.0 indican desviación clínica significativa.
            </p>
            """

        html_content += """
            <div class="qa-section">
                <h2>Control de Calidad (QA) FSL</h2>
        """
        
        descripciones_qa = {
            "I_bet.png": ("Extracción Craneal (HD-BET / Skull-Stripping)", "Muestra el parénquima cerebral aislado superpuesto sobre la resonancia magnética original. Permite al especialista verificar visualmente que el algoritmo no ha recortado tejido cortical válido ni ha incluido duramadre, cráneo o globos oculares.", "qa-image"),
            "I2std.png": ("Registro al Espacio Estándar (FLIRT MNI152)", "Verifica la alineación afín del cerebro del paciente (imagen de fondo) contra el atlas anatómico estándar MNI152 (bordes rojos). Este registro geométrico es el paso crítico que permite a SIENAX calcular el 'v_scale' (factor de normalización) para corregir el tamaño de la cabeza del paciente.", "qa-image"),
            "I_masks.png": ("Máscara de Cobertura (Field of View)", "Asegura que el cerebro extraído (azul) y la máscara del espacio estándar (líneas rojas) intersecan correctamente (zona verde). Garantiza que ninguna parte del encéfalo ha quedado fuera del campo de visión (FOV) del escáner durante el procesamiento.", "qa-image"),
            "I_render.png": ("Segmentación Final de Tejidos (FAST)", "Renderizado multicorte que visualiza la clasificación probabilística final de los vóxeles. Permite auditar la separación de los tejidos: Materia Gris, Materia Blanca y Líquido Cefalorraquídeo en los planos axiales, sagitales y coronales.", "qa-image-full")
        }

        for img_name, info in descripciones_qa.items():
            if img_name in imgs:
                titulo, descripcion, img_class = info
                img_data = _imagen_a_base64(imgs[img_name])
                style_body = ' style="flex-direction: column; align-items: flex-start;"' if img_class == "qa-image-full" else ''
                html_content += f"""
                <div class="qa-card">
                    <h3 class="qa-header">{titulo}</h3>
                    <div class="qa-body"{style_body}>
                        <p class="qa-description">{descripcion}</p>
                        <img class="{img_class}" src="{img_data}" alt="{titulo}">
                    </div>
                </div>
                """
        html_content += "<hr style='border:1px solid #ecf0f1; margin: 40px 0;'>"

    html_content += """
            </div>
            <div class="credits-section">
                <h3>Metodología Científica</h3>
                <p>El volumen del tejido cerebral, normalizado por el tamaño de la cabeza del sujeto, se estimó con la herramienta SIENAX, parte de la librería FSL. La extracción primaria del cerebro se delegó a la red neuronal artificial HD-BET para una mayor precisión. Posteriormente, la imagen se registró de forma afín al espacio estándar MNI152 para obtener el factor de escala volumétrico (V-scale), utilizado como normalización del tamaño craneal. Finalmente, la segmentación de tipos de tejido con estimación de volumen parcial se llevó a cabo mediante el algoritmo FAST.</p>
                <h3>Referencias</h3>
                <ul class="references">
                    <li><em>Smith, S.M., et al. (2002). Accurate, robust and automated longitudinal and cross-sectional brain change analysis. NeuroImage, 17(1):479-489.</em></li>
                    <li><em>Isensee, F., et al. (2019). Automated brain extraction of multisequence MRI using artificial neural networks. Human Brain Mapping, 40(17):4952-4964. (HD-BET)</em></li>
                    <li><em>Zhang, Y., et al. (2001). Segmentation of brain MR images through a hidden Markov random field model and the expectation maximization algorithm. IEEE Trans. on Medical Imaging, 20(1):45-57.</em></li>
                </ul>
                <h3>Desarrollo</h3>
                <p>Pipeline <strong>MedVision</strong> y generador de reportes HTML desarrollados por <strong>Miriam Rodríguez García</strong>.</p>
            </div>
        </div>
    </body>
    </html>
    """
    with open(ruta_informe_html, 'w', encoding='utf-8') as f:
        f.write(html_content)