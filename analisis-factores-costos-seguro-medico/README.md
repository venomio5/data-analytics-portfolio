# Análisis de factores que influyen en el costo de seguro médico

Las aseguradoras necesitan saber qué características de sus asegurados influyen más en los cargos médicos, y cuáles de ellas se pueden modificar para reducirlos. Limpié y exploré un dataset de 1,337 asegurados, y con la correlación y la comparación de cargos por grupo identifiqué el tabaquismo como el factor con mayor relación con los cargos. Para medirlo con más precisión construí un modelo de regresión polinomial con regularización Lasso (R² = 0.89), que captura las interacciones entre variables, como IMC × fumador. Con ese modelo predije los cargos y simulé escenarios de reducción de tabaquismo e IMC.

Estructura del proyecto:

```
├── data/               # Conjuntos de datos originales y procesados utilizados en el análisis.
├── notebooks/          # Cuadernos de Jupyter con las distintas etapas del análisis (exploración, visualización y modelado).
└── README.md
```

Para la historia completa, todas las visualizaciones y las recomendaciones en formato ejecutivo, visita la página de [Notion](https://www.notion.so/Health-Insurance-Cost-Drivers-Analysis-322b7682d7a780be93dfda917e97018d).
