# Research_Blender_MedVisor

Visualización de imágenes médicas con Blender. Automatiza el flujo de trabajo de segmentación médica permitiendo importar volúmenes de Resonancia Magnética (MRI) en formato NIfTI (`.nii.gz`), ejecutar la red neuronal HD-BET en segundo plano y generar automáticamente una malla 3D optimizada en el *viewport* de Blender junto a un entorno de visualización síncrono.

## Prerrequisitos del Sistema

Dado que el procesamiento pesado recae sobre modelos de Inteligencia Artificial, **MedVision requiere tener instalado HD-BET en tu sistema operativo** antes de usar el addon.

### Dependencias de Python e IA:
Para que HD-BET funcione correctamente, es requisito indispensable contar con **PyTorch**. Ten en cuenta que estas librerías de IA suelen ir un paso por detrás del desarrollo de software general, por lo que **no admiten las versiones más recientes de Python**. Asegúrate de instalarlo utilizando una versión de Python compatible y estable.

1. Instala la herramienta ejecutando: `pip install hd-bet` (asegurándote de tener PyTorch configurado previamente) o siguiendo las instrucciones de su repositorio oficial.
2. Anota la ruta completa donde se encuentra el ejecutable `hd-bet` (ej. `C:\Ruta\A\Tu\Python\Scripts\hd-bet.exe`).

> **Nota:** Si dispones de una GPU compatible con PyTorch (mediante CUDA), el procesamiento tardará menos. En caso de usar CPU, el proceso puede tardar unos minutos. Para más detalles, consulta el [repositorio oficial de HD-BET](https://github.com/MIC-DKFZ/hd-bet).

## Instalación del Addon en Blender

*Importante: Este addon ha sido desarrollado y validado para funcionar a partir de la versión **3.6** de Blender.*

1. Descarga el código de este repositorio como un archivo `.zip`.
2. Abre Blender.
3. Dirígete a **Edit > Preferences > Add-ons**.
4. Haz clic en **Install...** y selecciona el archivo `.zip`.
5. Activa la casilla `3D View: MedVision` para habilitarlo.

## Uso del Addon

Una vez activado, el addon configurará el entorno automáticamente:

1. El sistema creará un espacio de trabajo (*Workspace*) dedicado llamado **MedVision**, configurado automáticamente con vista cuádruple (*QuadView*) para análisis clínico simultáneo.
2. En el panel lateral derecho del *Viewport* (tecla `N`), busca la pestaña **MedVision Control**.
3. **Archivo MRI:** Utiliza el selector para elegir tu volumen en formato `.nii.gz`.
4. **Ruta HD-BET:** Indica la ruta completa al ejecutable de `hd-bet` que instalaste en tu sistema.
5. **Extraer Cerebro:** Haz clic en este botón. Blender ejecutará el proceso en segundo plano, segmentará el parénquima cerebral y renderizará la malla tridimensional centrada y orientada automáticamente en el centro de la escena.



## Arquitectura y Funcionamiento Interno

El núcleo de MedVision se divide en un pipeline de procesamiento de datos y un motor de renderizado en tiempo real optimizado para no generar objetos basura en la escena de Blender:

1. **Ingesta y Segmentación:** Al cargar el volumen NIfTI, el addon invoca el ejecutable de `HD-BET` a través de un subproceso asíncrono en segundo plano, aislando el tejido cerebral del cráneo.
2. **Estandarización Espacial:** El volumen segmentado se procesa mediante matrices de orientación clínica (espacio de coordenadas RPS/RAS). Esto garantiza la correspondencia anatómica exacta (saber inequívocamente dónde se ubican las regiones anterior, posterior, superior e inferior del paciente).
3. **Reconstrucción 3D:** Se aplica el algoritmo de *Marching Cubes* sobre los vóxeles indexados para extraer la superficie cerebral y transformarla en una malla de vértices nativa de Blender.
4. **Motor Slicer 2D (GPU Shaders):** Las lonchas bidimensionales correspondientes a los planos Axial, Coronal y Sagital se extraen de la matriz de NumPy en tiempo real. Mediante el módulo `gpu` de Blender, se inyectan como texturas directamente en el búfer de dibujo de la gráfica (`draw_handler`). 
   * Un lienzo opaco inteligente oculta de forma óptica la geometría 3D en las vistas ortogonales (`TOP`, `FRONT`, `RIGHT`), permitiendo inspeccionar las radiografías limpias y con un HUD de texto superpuesto mientras el modelo 3D permanece visible únicamente en la vista de perspectiva.

## Reconocimientos y Herramientas de Terceros

Este proyecto es posible gracias a la integración y el uso de herramientas especializadas de código abierto dentro de la comunidad científica y médica. Se otorga el correspondiente reconocimiento a:

* **[HD-BET (High-Definition Brain Extraction Tool)](https://github.com/MIC-DKFZ/HD-BET):** Desarrollado por el departamento de *Medical Image Computing* del DKFZ (Centro Alemán de Investigación Oncológica). MedVision utiliza este algoritmo de última generación basado en redes neuronales convolucionales (U-Net artificiales) para realizar la extracción craneal automatizada con precisión clínica.
* **[SimpleITK (Insight Segmentation and Registration Toolkit)](https://simpleitk.org/):** Componente esencial utilizado para la manipulación de imágenes médicas y el procesamiento de los metadatos de orientación espacial de los archivos NIfTI.
* **[NumPy](https://numpy.org/):** Utilizado para la gestión matricial de alta velocidad de los vóxeles tridimensionales, permitiendo aplicar las operaciones de transposición y rotación necesarias para sincronizar los planos de corte con las ventanas de Blender.

## Limitaciones y Alcance

* **Modalidad:** Pipeline validado exclusivamente para volúmenes de **Resonancia Magnética (MRI)**.
* **Formatos incompatibles:** El uso de datos basados en densidad radiológica, como la Angiotomografía (CTA) o PET, no es compatible con el modelo de segmentación actual.
