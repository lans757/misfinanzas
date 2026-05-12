# Guía de usuario — MisFinanzas

## ¿Qué es MisFinanzas?

Una app web personal para registrar tus ingresos y gastos en Venezuela. Soporta bolívares (Bs), dólares (USD) y USDT, con tasas de cambio en tiempo real del BCV y Binance P2P.

---

## Primeros pasos

### 1. Crear tu cuenta

Al abrir la app verás la pantalla de acceso. Elegí **Registrarse**, completá usuario y contraseña (mínimo 6 caracteres) y hacé clic en **Crear cuenta**.

> Tu cuenta es privada: ningún otro usuario puede ver tus datos.

### 2. Pantalla principal

Una vez dentro, verás cinco pestañas en la barra superior:

| Pestaña | Qué hace |
|---------|---------|
| **Dashboard** | Resumen general, gráficos y alertas |
| **Movimientos** | Lista completa de transacciones |
| **Ahorros** | Saldo USDT y metas de ahorro |
| **Presupuestos** | Límites mensuales por categoría |
| **✨ IA** | Asistente financiero con Gemini |

---

## Registrar un movimiento

1. Ir a **Movimientos** → clic en **+ Agregar**
2. Elegir **Ingreso** o **Gasto**
3. Completar los campos:
   - **Descripción**: texto libre (ej: "Sueldo quincena")
   - **Categoría**: elegir de la lista predefinida
   - **Monto y moneda**: podés ingresar en Bs, USD o USDT
   - **Tasas de cambio**: si el monto es en USD o USDT, la app pide la tasa para calcular el equivalente en Bs. Usá el botón **Usar actual** para cargar la tasa del momento.
   - **Fecha**: por defecto es ahora, pero podés cambiarla
   - **Tags**: palabras clave separadas por coma (ej: `trabajo, viaje`)

4. Clic en **Registrar**

### Editar un movimiento

En la tabla de Movimientos, clic en el ícono **✎** de la fila correspondiente. Se abre el mismo formulario pre-cargado con los datos existentes.

### Eliminar un movimiento

Clic en **✕** al final de la fila → confirmar.

---

## Exportar a CSV

En la pestaña **Movimientos**, botón **↓ CSV** en la barra superior. Descarga un archivo `.csv` con todos tus movimientos. Se puede abrir directamente en Excel o Google Sheets.

---

## Tasas de cambio

En el encabezado (siempre visible) se muestran las tasas actuales. El botón **↻** actualiza ambas tasas.

- **BCV**: dólar oficial venezolano (fuente: dolarapi.com)
- **Binance P2P**: promedio de las 5 mejores ofertas de compra USDT/VES

Las tasas se guardan automáticamente cada vez que se actualizan. El gráfico de historial en el Dashboard muestra la evolución.

---

## Dashboard

El Dashboard muestra cuatro cards de resumen:

- **Saldo en Bs**: diferencia entre ingresos y gastos históricos totales
- **Equivalente USD**: saldo convertido al BCV actual
- **Saldo USDT**: suma de todos los movimientos en USDT
- **Gastos este mes**: total de gastos en el mes calendario actual

### Alertas de presupuesto

Si configuraste presupuestos y alguna categoría superó el 80% del límite este mes, aparece un bloque rojo con barras de progreso debajo de las cards.

### Gráficos

- **Flujo mensual**: barras comparando ingresos vs gastos por mes (últimos 6 meses)
- **Gastos por categoría**: dona con los 8 rubros con más gasto acumulado
- **Historial de tasas**: líneas de BCV y Binance a lo largo del tiempo (aparece después de varias actualizaciones de tasas)

---

## Ahorros

La pestaña Ahorros muestra:

1. **Saldo USDT** en grande, con equivalente en Bs y USD
2. **Metas de ahorro**: objetivos personales expresados en USDT

### Crear una meta

Clic en **+ Nueva meta** → completar nombre y objetivo en USDT → **Crear meta**.

La app calcula automáticamente el porcentaje alcanzado comparando tu saldo USDT actual con el objetivo. Cuando llegás al 100%, aparece "¡Meta alcanzada! 🎉".

---

## Presupuestos

Los presupuestos te permiten definir cuánto querés gastar por categoría al mes.

### Crear un presupuesto

1. Elegir la categoría del menú desplegable
2. Ingresar el límite mensual en Bs
3. Clic en **+ Agregar**

> Si ya existe un presupuesto para esa categoría, el nuevo límite reemplaza al anterior.

### Ver el estado

Las barras de progreso muestran cuánto gastaste este mes en cada categoría:
- 🟢 Verde: por debajo del 80%
- 🟡 Amarillo: entre 80% y 100%
- 🔴 Rojo: superado

Las categorías en rojo o amarillo también aparecen como alertas en el **Dashboard**.

---

## Asistente IA

El asistente usa Google Gemini y tiene acceso completo a tus datos financieros: saldo, ingresos, gastos, categorías, movimientos recientes y tasas actuales.

### Configurar la API key (una sola vez)

1. Ir a [aistudio.google.com](https://aistudio.google.com)
2. Iniciar sesión con tu cuenta Google
3. Clic en **Get API Key** → **Create API key**
4. Copiar la key y pegarla en la pestaña **✨ IA** → **Guardar y activar**

El plan gratuito incluye 1 millón de tokens por día, más que suficiente para uso personal.

### Preguntas de ejemplo

- *"¿Cuánto gasté este mes?"*
- *"¿En qué categoría gasto más?"*
- *"¿Cómo están mis ahorros en USDT comparado con el mes pasado?"*
- *"Dame tres consejos de ahorro basados en mis datos"*
- *"¿Puedo permitirme gastar $200 este fin de semana?"*

---

## Preguntas frecuentes

**¿Mis datos están seguros?**
Sí. Cada usuario solo puede ver sus propios datos. Las contraseñas se guardan con hash bcrypt, nunca en texto plano.

**¿Qué pasa si no ingreso la tasa de cambio al registrar en USD/USDT?**
La app te lo va a pedir — es un campo requerido para esas monedas, porque sin él no puede calcular el equivalente en Bs.

**¿Puedo cambiar la fecha de un movimiento?**
Sí. Al editar (botón ✎) podés modificar la fecha y hora.

**¿Los tags sirven para filtrar?**
Sí. El buscador en Movimientos busca tanto en la descripción como en los tags.

**¿Qué pasa si cierro sesión?**
El token queda invalidado en el browser. Tus datos en el servidor permanecen intactos.
