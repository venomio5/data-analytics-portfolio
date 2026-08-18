# Análisis de Rotación de Inventario

Este proyecto resuelve un problema crítico de retail: la gestión de inventario basada en intuición, que genera quiebres de stock o capital inmovilizado. A partir de casi 30,000 registros históricos de cinco sucursales (Cancún, Cancún Centro, Mérida Centro, Mérida Norte y Playa del Carmen), se construyó un modelo predictivo de ventas con **LightGBM **y función de pérdida **Tweedie** para manejar la alta presencia de ceros y los picos de demanda típicos del sector.

Se aplicó ingeniería de características cíclicas (seno/coseno) sobre mes y día de la semana para capturar estacionalidades, y se entrenó con validación temporal (`TimeSeriesSplit`) y búsqueda de hiperparámetros (`RandomizedSearchCV`). El modelo final predice la demanda futura con un error absoluto medio de 6.87 unidades (~30% del volumen promedio).

Con esas proyecciones se calcula la **rotación de inventario proyectada** (días de inventario disponibles según demanda esperada a 30 días) y se genera una **sugerencia de pedido automática**, todo integrado en un dashboard de Power BI con semáforos de urgencia y sobrestock. El dueño ya no adivina: abre el tablero, ve los productos en rojo y sabe exactamente qué pedir.

Estructura del proyecto:

```
analisis-rotacion-inventario/
│
├── data/
│ ├── data.csv # Histórico de ventas (fecha, sucursal, producto, unidades)
│ └── inventario_demanda.csv # Inventario actual y demanda histórica por producto/sucursal
│
├── notebooks/
│ ├── modeling_lgbm.ipynb # Análisis exploratorio, ingeniería de características,
│ │ # entrenamiento del modelo LightGBM y evaluación
│ └── ventas_prediction.py # Script productivo para predicción masiva de ventas a futuro
│
├── reports/
│ ├── Reporte_Inventario_v1.pbix # Dashboard de Power BI con KPIs, semáforos y sugerencias de pedido
│ └── README.md # Este documento
│
└── .gitignore
```

Para más detalles revisa la[ página de Notion](https://app.notion.com/p/An-lisis-de-Rotaci-n-de-Inventario-392b7682d7a7804c9e7de903430dbc3b).
