# Textos del proyecto: Análisis de Rotación de Inventario

---

## Versión larga (Notion)

**Resultado clave (propiedad de la base de datos):**
Tablero que dice por producto y sucursal qué pedir, cuánto y a quién; la proyección de demanda tiene 25% menos error que repetir la venta de la semana anterior.

> 📋 **Resumen**
>
> - **Problema:** una distribuidora con cinco sucursales en Cancún, Playa del Carmen y Mérida hacía sus pedidos a ojo: se le acababan los productos que más se venden y acumulaba los que casi no se mueven.
> - **Enfoque:** limpié 18 meses de ventas e inventario diario, comparé 11 métodos de proyección contra las ventas reales de 2024 y llevé el mejor a Power BI con reglas de pedido, exceso y transferencias entre sucursales.
> - **Resultado:** un tablero que responde por producto y sucursal si hay que pedir, cuánto y a qué proveedor, y dónde hay dinero parado en bodega.
> - **Herramientas:** Python, Power BI y DAX.

Una distribuidora de abarrotes, bebidas, lácteos, higiene y limpieza, con cinco sucursales (Cancún, Cancún Centro, Playa del Carmen, Mérida Centro y Mérida Norte) y cinco proveedores, decidía sus pedidos por intuición. Algunos productos se agotaban antes de que llegara el pedido y otros se quedaban meses en bodega con dinero inmovilizado. El dueño necesitaba responder tres preguntas cada semana: ¿hay que pedir?, ¿cuánto y a quién?, y ¿dónde me sobra mercancía?

**Procedimiento**

1. **Limpieza de datos (Python).** Partí de 53,587 registros diarios de ventas e inventario, de enero de 2023 a junio de 2024. Las categorías venían escritas de 20 formas distintas y las sucursales de 22 (mayúsculas, acentos, singular y plural); las normalicé a 5 y 5. Eliminé fechas incompletas (solo año y mes) y duplicados, marqué los proveedores faltantes como "N/A" y llené con 0 las unidades recibidas vacías. Quedaron 52,739 registros limpios.
2. **Análisis exploratorio.** Comparé las ventas por sucursal, por día de la semana y por mes. Las sucursales y los días se comportan casi igual; la diferencia está en el mes, y cada producto tiene su propia temporada. El agua de sabor vende 47% más que su promedio en julio, mientras que el aceite sube 20% en noviembre, diciembre y enero, y cae 24% en junio.
3. **Proyección de demanda.** Agrupé las ventas por semana y probé 11 métodos: promedios móviles de 1 a 52 semanas, mezclas entre ellos y mezclas ajustadas con un índice estacional por producto. Calculé el índice con 2023 y medí el error contra las semanas reales de 2024. Ganó la mezcla del promedio de 4 y 52 semanas, ajustada con la mitad del índice estacional: se equivoca en promedio 20.1 unidades por semana, frente a 26.9 de repetir la venta de la semana anterior, y casi sin sesgo (+0.8 unidades). Elegí un método sencillo a propósito: el dueño lo puede entender y se puede replicar en Power BI.
4. **Modelo en Power BI.** Construí un esquema estrella y repliqué la proyección en DAX con dos tablas calculadas (índice estacional y proyección de las próximas 4 semanas). Se recalculan solas al cargar datos nuevos, sin volver a correr el notebook.
5. **Reglas de negocio (DAX).**
    - **Cuándo pedir:** cuando el inventario no alcanza para 7 días más los días de entrega del proveedor (de 3 a 7 días, más 2 en diciembre y Semana Santa, que se calcula sola cada año).
    - **Cuánto pedir:** 7 días de demanda proyectada, con un colchón de 10% en agua y cerveza.
    - **Exceso:** inventario por encima de 7 días en lácteos, 30 en abarrotes y 14 en el resto, valuado a costo.
    - **Transferencias:** si una sucursal tiene que pedir y otra de su misma zona tiene exceso del producto, el tablero lo sugiere.
6. **Documentación.** Escribí un manual con las tablas, las medidas y las reglas del modelo, cada una con el lugar donde se cambia, para que se pueda mantener sin mí.

**Resultado**

Un tablero en Power BI con una matriz por sucursal: inventario actual, demanda diaria proyectada, días de inventario con semáforo, proveedor, días de entrega, unidades a pedir, transferencia sugerida y valor en exceso. Los estados usan formas distintas (▲ urgente, ● pedir, ■ exceso) para que se lean aunque el reporte se imprima en blanco y negro. Algunos ejemplos de la sucursal Cancún:

- **Agua Mineral 1L:** le queda 1.1 días de inventario y el proveedor tarda 7 en entregar. Urgente: pedir 302 unidades.
- **Aceite Vegetal 1L:** hay que pedir 59 unidades, pero Playa del Carmen tiene 88 de más; conviene transferir antes de comprar.
- **Desodorante Spray 150ml:** tiene inventario para 1,434 días, \$56.7 mil parados en bodega.
- **Valor total en exceso:** \$185.7 mil.

El dueño ya no adivina: abre el tablero, ve qué está en rojo y sabe exactamente qué pedir y a quién.

![](reports/inventario.png)

---

*Nota: los datos de este proyecto son sintéticos, generados para replicar un escenario de negocio realista.*

---

## Versión corta (README y currículum)

### README

````markdown
# Análisis de Rotación de Inventario

![Dashboard de inventario](reports/inventario.png)

Una distribuidora con cinco sucursales en Cancún, Playa del Carmen y Mérida hacía sus pedidos a ojo: se le acababan los productos que más se venden y acumulaba los que casi no se mueven. Limpié 18 meses de ventas e inventario diario en Python, comparé 11 métodos de proyección contra las ventas reales de 2024 y elegí una mezcla de promedios móviles con índice estacional, que tiene 25% menos error que repetir la venta de la semana anterior. La repliqué en Power BI con DAX junto con las reglas de negocio. El resultado es un tablero que dice por producto y sucursal si hay que pedir, cuánto y a qué proveedor, dónde hay dinero parado en exceso y qué sucursal puede transferir mercancía antes de comprar

→ **[Caso completo en Notion](https://app.notion.com/p/An-lisis-de-Rotaci-n-de-Inventario-392b7682d7a7804c9e7de903430dbc3b)**

---

Estructura del proyecto:

```
analisis-rotacion-inventario-distribuidora/
│
├── data/
│   ├── _raw/
│   │   └── inventario_demanda.csv              # Ventas e inventario diario por producto y sucursal
│   └── processed/
│       └── inventario_demanda_limpio.parquet   # Datos limpios
│
├── notebooks/
│   ├── 01_data_cleaning.ipynb                  # Limpieza y estandarización
│   ├── 02_eda.ipynb                            # Ventas por sucursal, día de la semana y mes
│   └── 03_proyeccion.ipynb                     # Comparación de 11 métodos de proyección
│
└── reports/
    ├── inventario.pbix                         # Dashboard de Power BI
    ├── inventario.png                          # Captura del dashboard
    └── Documentacion_Modelo_Inventario.docx    # Tablas, medidas y reglas de negocio
```
````

### Currículum

**Análisis de Rotación de Inventario** · Python, Power BI, DAX
Construí un tablero de reabasto para una distribuidora con cinco sucursales que hacía sus pedidos a ojo. Comparé 11 métodos de proyección de demanda y el elegido tiene 25% menos error que repetir la venta anterior. El tablero indica qué pedir, cuánto y a qué proveedor, y detecta inventario en exceso y transferencias entre sucursales.
