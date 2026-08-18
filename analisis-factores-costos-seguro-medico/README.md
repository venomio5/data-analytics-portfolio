# Análisis de factores que influyen en el costo de seguro médico

Las primas del seguro de salud de la empresa aumentaron recientemente un **15%**. Para ayudar a controlar futuros incrementos y reducir el costo por empleado, se analizó la base de datos interna con información demográfica y gastos médicos asociados.

El objetivo fue identificar los **principales factores determinantes de los costos** sobre los que se puede actuar mediante campañas de bienestar específicas. Utilizando un modelo de regresión Lasso con características polinómicas y análisis SHAP, se identificó que el **hábito de fumar** es, por mucho, la palanca más impactante. La recomendación final es implementar una **campaña antitabaco** enfocada en empleados fumadores, lo que permitiría reducir significativamente los cargos por empleado y compensar el alza de las primas.

Estructura del proyecto:

```
├── data/               # Conjuntos de datos originales y procesados utilizados en el análisis.
├── notebooks/          # Cuadernos de Jupyter con las distintas etapas del análisis (exploración, visualización y modelado).
├── reports/figures/    # Gráficas y figuras clave generadas para la presentación de resultados.
└── README.md
```

Para la historia completa, todas las visualizaciones y las recomendaciones en formato ejecutivo, visita la página de [Notion](https://www.notion.so/Health-Insurance-Cost-Drivers-Analysis-322b7682d7a780be93dfda917e97018d).
