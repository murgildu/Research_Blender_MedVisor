# Research_Blender_MedVisor
Medical image visualization with Blender

Características actuales:
* **Estructura Modular:** El código base está dividido en `__init__.py`, `paneles_ui.py` y `procesar_dicom.py` para facilitar la escalabilidad y el mantenimiento.
* **Configuración de Entorno Médico:** Al ejecutar la herramienta, el addon limpia la escena por defecto y divide el área de trabajo en 4 vistas médicas de forma automática, integrando el HUD.
* **Procesamiento de imagen:** Funciones para la lectura de directorios DICOM y algoritmos de segmentación 3D mediante umbrales (Thresholding) enfocados en la extracción de estructuras anatómicas.

Uso:
Una vez instalado y activado, el panel de control de MedVision aparecerá en la barra lateral derecha de la vista 3D (puedes desplegarla pulsando la tecla `N`). Desde ahí podrás establecer la ruta de tu carpeta DICOM y utilizar los botones de configuración y extracción.
