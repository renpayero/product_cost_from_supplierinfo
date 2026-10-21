- **Desde los precios de proveedor** (*Compras > Configuración > Listas de
  precios de proveedores*): seleccionar las filas y usar *Acción > Tomar el
  costo del precio de proveedor*. Cada fila da el costo de su producto; una fila
  sin variante vale para todas las variantes de la plantilla. Si el proveedor de
  la fila no es el proveedor principal del producto (el primero de la pestaña
  *Compra* con un precio vigente hoy), la línea queda marcada.
- **Desde los productos** (lista de productos o de variantes): seleccionar los
  productos y usar la misma acción. Toma el proveedor principal de cada
  producto, el que usa Odoo cuando repone sin un proveedor fijo: la primera fila
  válida de la pestaña *Compra* del producto (por secuencia) y, de ese
  proveedor, el precio más bajo para la *Cantidad de compra* (1 por defecto). No
  es el que usa una orden de compra, que usa siempre su propio proveedor. No se
  usan los precios cuyo mínimo supera la cantidad de compra.
- Si varios proveedores comparten el primer lugar (la misma secuencia), Odoo
  elige por el orden de la lista (primero la cantidad mínima mayor y después el
  precio más bajo antes de la bonificación): la línea queda marcada, para que se
  defina el orden de los proveedores del producto. Desde los productos también
  queda marcada cuando el primer proveedor del producto no tiene un precio
  vigente hoy para esa cantidad y se usa el de otro.
- En la ventana se puede elegir:
  - *Precio de venta en*: opcional, muestra el precio de venta actual y el
    nuevo en esa lista de precios, calculado sin escribir nada;
  - *Marcar variaciones mayores a (%)*: 30 % por defecto. Los productos que lo
    superan quedan marcados y sin seleccionar, para revisarlos de a uno. Ahí
    caen, por ejemplo, los precios por caja cargados como precios por unidad.
- *Vista previa* muestra una línea por producto, con la acción (*Actualizar*,
  *Sin cambios* u *Omitir*) y el motivo. Solo se aplican las líneas con
  *Aplicar* tildado; *Seleccionar todo*, *No seleccionar ninguno* y *Quitar los
  marcados* ayudan a elegirlas.
- Se omiten, con el motivo: proveedor archivado, precio de otra compañía,
  precio en cero, producto archivado o de otra compañía, unidades de medida
  incompatibles, moneda sin tipo de cambio, método de costo FIFO o promedio
  (ese costo lo calcula Odoo), costo negativo y dos precios elegidos para el
  mismo producto. Desde los productos también se omiten los que no tienen un
  precio de proveedor válido hoy para esa cantidad y esa compañía.
- Se marcan, sin seleccionar: los precios que no están vigentes hoy, las
  variaciones mayores al umbral, los precios de un proveedor que no es el
  principal, los proveedores empatados en el primer lugar y, desde los
  productos, el primer proveedor sin precio vigente hoy.
- *Aplicar* vuelve a leer el costo y el método de costo de cada producto y, si
  el costo cambió después de la vista previa o el producto pasó a costo FIFO o
  promedio, lo deja como está. Los que ya tienen el costo nuevo no se vuelven a
  escribir, y apretar *Aplicar* otra vez en la misma ventana no toca nada: avisa
  que esa vista previa ya se aplicó. Escribe el costo en cada variante, en la
  compañía elegida. Con Inventario instalado, Odoo registra cada cambio en su
  historial de costos.
- El aviso de *Aplicar* trae un enlace a la actualización creada. *Compras >
  Productos > Actualizaciones de costo* (hace falta acceso a Compras para ver
  ese menú) lista las actualizaciones, con el costo anterior y el nuevo de cada
  producto; para los administradores de productos son de solo lectura.
- *Revertir* devuelve el costo anterior a los productos que siguen con el costo
  de esa actualización, que ninguna actualización posterior volvió a cambiar y
  que siguen con costo estándar; los demás quedan como están, con una nota. Un
  aviso dice cuántos se revirtieron y cuántos quedaron como estaban; si no se
  revirtió ninguno, el estado no cambia. Para deshacer una actualización con
  otras posteriores sobre los mismos productos, primero hay que revertir las
  posteriores.
- Solo los administradores de productos ven la acción.
