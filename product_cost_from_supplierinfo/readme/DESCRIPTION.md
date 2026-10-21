Este módulo pasa el precio del proveedor al costo de los productos, con una
vista previa y la posibilidad de deshacer el cambio.

Odoo guarda los precios de los proveedores (*Compras > Configuración > Listas
de precios de proveedores*), pero no los copia al costo del producto: cargar o
actualizar la lista de un proveedor no cambia ningún costo. Si el precio de
venta se calcula sobre el costo (una regla "Fórmula" basada en el costo), hay
que actualizar los costos de a uno.

Con este módulo, la acción *Tomar el costo del precio de proveedor* calcula el
costo neto de cada producto, el mismo con el que Odoo valoraría la recepción de
una compra de una unidad:

- aplica la posición fiscal del proveedor a los impuestos de compra;
- redondea el precio del proveedor en su moneda, como el precio unitario de una
  línea de orden de compra;
- resta la bonificación (el campo *Descuento* del precio de proveedor);
- quita los impuestos incluidos en el precio y suma la parte no deducible de
  los impuestos (las líneas de distribución sin cuenta);
- convierte el precio a la unidad del producto (por ejemplo, de una caja de 12
  a una unidad) y a la moneda de la compañía;
- redondea a la precisión de "Precio de producto".

Antes de escribir muestra una vista previa con el costo actual, el costo nuevo
y la variación de cada producto y, si se elige una lista de precios, el precio
de venta actual y el nuevo. Cada actualización queda registrada en *Compras >
Productos > Actualizaciones de costo*, desde donde se puede revertir.
