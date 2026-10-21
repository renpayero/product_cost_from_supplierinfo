==============================
Product Cost from Supplierinfo
==============================

.. |badge1| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
    :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
    :alt: License: AGPL-3
.. |badge2| image:: https://img.shields.io/badge/github-renpayero%2Fproduct__cost__from__supplierinfo-lightgray.png?logo=github
    :target: https://github.com/renpayero/product_cost_from_supplierinfo/tree/19.0
    :alt: renpayero/product_cost_from_supplierinfo

|badge1| |badge2|

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

**Índice**

.. contents::
   :local:

Uso
===

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

Limitaciones conocidas
======================

- El costo es el de una unidad comprada hoy. Los impuestos de monto fijo
  también son por unidad, así que no cambian el costo de una compra de varias
  unidades; en esa compra solo puede variar el redondeo a centavos de la parte
  no deducible de los impuestos.
- El precio del proveedor se redondea como en una orden de compra hecha en la
  moneda del proveedor. Si la orden se hace en otra moneda, Odoo redondea
  después de convertir, y el costo puede diferir en el último decimal del de esa
  recepción.
- Los productos con costo FIFO o promedio se omiten: ese costo lo calcula Odoo
  con las recepciones.
- La caja guarda sus datos en el navegador. Cuando se actualiza alguno de sus
  productos, las cajas cuyos precios dependen del costo (las que aplican una
  lista con una regla basada en el costo, o una lista basada en otra así)
  quedan marcadas para recargar todo, pero los costos nuevos llegan recién
  cuando la caja se abre de nuevo desde el tablero del punto de venta o cuando
  empieza una sesión nueva: refrescar la página (F5) no recarga nada. Esa
  recarga borra en ese navegador todos los pedidos que todavía no se enviaron
  al servidor (el pedido en curso, los pedidos abiertos que no se guardaron
  para después y los pedidos cobrados que no se pudieron enviar): antes de
  volver a abrir la caja hay que terminarlos o guardarlos para después. Las
  demás cajas no se recargan: sus precios no cambian, pero la información del
  producto (costo y margen) sigue mostrando el costo anterior.
- Con Inventario, cada costo que cambia pasa por la revaloración de Odoo
  (historial de costos y movimientos de stock pendientes de valorar), así que
  aplicar miles de costos distintos lleva tiempo. Detrás de un proxy con tiempo
  de espera (por ejemplo, 60 segundos) conviene aplicar por proveedor o por
  marca: reintentar es seguro, lo que ya tiene el costo nuevo no se vuelve a
  escribir.
- Desinstalar el módulo borra las actualizaciones de costo registradas. El
  historial de costos de Odoo se conserva.

Alternativas evaluadas y no implementadas, para decidir más adelante:

- Que la caja tome el costo nuevo con su carga parcial, sin recarga completa:
  después de confirmar, marcar como modificadas las plantillas y las variantes
  actualizadas. La carga parcial que hace la caja al abrirse desde el tablero,
  o en una sesión nueva, las trae con el costo nuevo y no borra ningún pedido.
  Falta comprobarlo en el navegador de la caja, y cambia la fecha de última
  modificación de esos productos.
- Postergar la recarga de la caja hasta que no haya sesiones abiertas:
  cuidaría los pedidos guardados en el navegador, pero los costos nuevos no
  entrarían durante el día, y necesitaría engancharse en la sesión de la caja
  para no competir con un cambio de turno.

Historial de cambios
====================

19.0.1.0.0
----------

- Primera versión.

Reporte de errores
==================

Los errores se reportan en `GitHub Issues <https://github.com/renpayero/product_cost_from_supplierinfo/issues>`_.

Créditos
========

Autores
-------

- Renzo Payero
- DakoDev

Colaboradores
-------------

- Renzo Payero <rpayerodev@gmail.com> (DakoDev)
