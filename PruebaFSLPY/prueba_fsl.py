import time
import os
from fsl.wrappers import fast
from fsl.wrappers.fslstats import fslstats

def ejecutar_prueba_fsl(input_nifti, output_dir):
    print(f"--- Iniciando prueba de segmentación con FSL (FAST) ---")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    prefijo_salida = os.path.join(output_dir, "fsl_seg")
    
    #para el tiempo
    inicio_tiempo = time.time()
    
    try:
        # Ejecutar FAST para las 3 clases (GM, WM, CSF)
        fast(imgs=input_nifti, out=prefijo_salida, n_classes=3)
        
        fin_tiempo = time.time()
        tiempo_total = fin_tiempo - inicio_tiempo
        print(f"[ÉXITO] Segmentación completada en {tiempo_total:.2f} segundos.")
        
        # archivos terminados
        mapa_gm = f"{prefijo_salida}_pve_1.nii.gz"
        
        if os.path.exists(mapa_gm):
            # -M (Media no cero) * -V (Volumen en mm3)
            volumen_gm = fslstats(mapa_gm).V.run()
            print(f"Datos extraídos - Volumen (vóxeles, mm3): {volumen_gm}")
            
    except Exception as e:
        print(f"[ERROR] Falló la ejecución de FAST: {e}")

if __name__ == "__main__":
    # ruta de archivo limpio
    archivo_entrada = "/mnt/d/Apps/HdBet/data/cerebro_limpio_mri.nii.gz"
    directorio_salida = "./resultados_fsl"
    ejecutar_prueba_fsl(archivo_entrada, directorio_salida)