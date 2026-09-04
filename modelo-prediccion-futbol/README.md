# Modelo de Predicción de Fútbol

Este proyecto nació de la intuición de que el mercado de apuestas no refleja con precisión lo que realmente ocurre dentro de un partido de fútbol. Para explotar esa ineficiencia, se construyó un pipeline algorítmico de principio a fin que genera “líneas justas” calibradas y las compara con las cuotas de las casas de apuestas en mercados de alta liquidez (1X2, Over/Under 2.5, Asian Handicap, entre otros).
En esencia, se toma un partido con todas sus variables (jugadores, contexto, dinámica del juego) y se traduce a una simulación Monte Carlo que corre el encuentro miles de veces para obtener probabilidades exactas de cada resultado. Esas probabilidades, cuando difieren de las cuotas de mercado, representan una ventaja medible.

Estructura del repositorio:

```
├── assets/          # Gráficos e imágenes del análisis
├── data/            # Datos utilizados en los notebooks (muestra o agregados)
├── notebooks/       # Notebooks con visualizaciones y resultados del backtest
├── .gitignore
└── README.md
```

> **Nota importante:** Este repositorio público muestra únicamente los resultados y algunas visualizaciones. El código fuente del modelo, los algoritmos de machine learning y la implementación completa se encuentran en un repositorio privado. Por su naturaleza como modelo en producción, se mantiene confidencial.

El desglose total de la metodología, los análisis de rendimiento, gráficos interactivos y la historia detrás del proyecto están disponibles en la pagina de **[Notion](https://www.notion.so/Advanced-Soccer-Forecasting-Model-322b7682d7a780b7a49ac85b794058a8)**.
