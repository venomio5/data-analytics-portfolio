import pandas as pd
import numpy as np
import lightgbm as lgb
from itertools import product

# 1. Purgar el peso muerto y renombrar
columnas_basura = ['costo_unitario', 'importe_costo', 'importe_venta', 
                   'precio_unitario', 'proveedor', 'Stock_cierre', 'unidades_recibidas']
df = dataset.drop(columns=columnas_basura, errors='ignore').copy()
df = df.rename(columns={"unidades_vendidas": "ventas"})

df['ventas'] = df['ventas'].fillna(0)
df['fecha'] = pd.to_datetime(df['fecha'])

# 2. Extraer límites de realidad
año_minimo = df['fecha'].dt.year.min()
fecha_minima = df['fecha'].min()
fecha_maxima = df['fecha'].max()
fecha_futuro = fecha_maxima + pd.DateOffset(years=1)

productos_unicos = df['id_producto'].dropna().unique()
sucursales_unicas = df['id_sucursal'].dropna().unique()

# 3. Preparar los datos históricos para entrenar
df['año'] = df['fecha'].dt.year
df['tendencia_anual'] = df['año'] - año_minimo

df['mes_sin'] = np.sin(2 * np.pi * df['fecha'].dt.month / 12)
df['mes_cos'] = np.cos(2 * np.pi * df['fecha'].dt.month / 12)
df['dia_sin'] = np.sin(2 * np.pi * df['fecha'].dt.dayofweek / 7)
df['dia_cos'] = np.cos(2 * np.pi * df['fecha'].dt.dayofweek / 7)

# Aislar variables de entrenamiento
X_train = df[['id_producto', 'id_sucursal', 'tendencia_anual', 
              'mes_sin', 'mes_cos', 'dia_sin', 'dia_cos']].copy()
y_train = df['ventas']

# Categorizar nativamente para LightGBM
X_train['id_producto'] = X_train['id_producto'].astype('category')
X_train['id_sucursal'] = X_train['id_sucursal'].astype('category')

# 4. Entrenar el modelo con los parámetros óptimos
lgbm = lgb.LGBMRegressor(
    objective='tweedie',
    tweedie_variance_power=1.413334819346127,
    learning_rate=0.02864954741195319,
    min_child_samples=25,
    n_estimators=168,
    num_leaves=22,
    n_jobs=-1
)
lgbm.fit(X_train, y_train)

# 5. CONSTRUIR EL FUTURO (Producto Cartesiano)
# Esto crea una fila para cada día x cada producto x cada sucursal
rango_fechas = pd.date_range(start=fecha_minima, end=fecha_futuro, freq='D')
master_grid = pd.DataFrame(list(product(rango_fechas, productos_unicos, sucursales_unicas)), 
                           columns=['fecha', 'id_producto', 'id_sucursal'])

# 6. Replicar la ingeniería de características en el calendario maestro
master_grid['año'] = master_grid['fecha'].dt.year
master_grid['tendencia_anual'] = master_grid['año'] - año_minimo

master_grid['mes_sin'] = np.sin(2 * np.pi * master_grid['fecha'].dt.month / 12)
master_grid['mes_cos'] = np.cos(2 * np.pi * master_grid['fecha'].dt.month / 12)
master_grid['dia_sin'] = np.sin(2 * np.pi * master_grid['fecha'].dt.dayofweek / 7)
master_grid['dia_cos'] = np.cos(2 * np.pi * master_grid['fecha'].dt.dayofweek / 7)

# Preparar las columnas exactamente igual que X_train
X_master = master_grid[['id_producto', 'id_sucursal', 'tendencia_anual', 
                        'mes_sin', 'mes_cos', 'dia_sin', 'dia_cos']].copy()
X_master['id_producto'] = X_master['id_producto'].astype('category')
X_master['id_sucursal'] = X_master['id_sucursal'].astype('category')

# 7. Ejecutar las predicciones en el calendario maestro
master_grid['prediccion_ventas'] = np.round(lgbm.predict(X_master))

# Asegurar que no existan predicciones negativas
master_grid['prediccion_ventas'] = master_grid['prediccion_ventas'].clip(lower=0)

# 8. Unir la realidad con la predicción
# Hacemos un Left Join histórico para tener ambas columnas lado a lado
ventas_historicas = df[['fecha', 'id_producto', 'id_sucursal', 'ventas']]
final_df = pd.merge(master_grid, ventas_historicas, on=['fecha', 'id_producto', 'id_sucursal'], how='left')

# final_df es lo que Power BI va a capturar