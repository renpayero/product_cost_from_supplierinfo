# product_cost_from_supplierinfo

Módulo para **Odoo 19 Community**: pasa el **precio del proveedor al costo** de los productos, con
una vista previa y la posibilidad de **deshacer** el cambio.

## El problema

Odoo guarda los precios de los proveedores en *Compras > Configuración > Listas de precios de
proveedores*, pero **no los copia al costo** del producto. Cargar o actualizar la lista de un
proveedor no cambia ningún costo.

Cuando el precio de venta se calcula sobre el costo (una regla "Fórmula" basada en el costo), cada
lista nueva de un proveedor obliga a actualizar los costos de a uno, producto por producto.

## Cómo funciona

La acción **"Tomar el costo del precio de proveedor"** calcula el **costo neto** de cada producto:
el mismo con el que Odoo valoraría la recepción de una compra de una unidad (lo que hace
`purchase_stock` al recibir una orden de compra).

1. **Impuestos:** la posición fiscal del proveedor reemplaza los impuestos de compra del producto,
   como en una orden de compra.
2. **Precio unitario:** el precio del proveedor se redondea en su moneda, como el precio unitario
   de una línea de orden de compra (a los decimales de la moneda o de "Precio de producto", los
   que sean más).
3. **Bonificación:** se resta el *Descuento* del precio de proveedor.
4. **Impuestos incluidos y no deducibles:** se quitan los impuestos incluidos en el precio y se
   suma la parte de los impuestos que no es deducible (las líneas de distribución sin cuenta). El
   IVA recuperable no forma parte del costo.
5. **Unidad y moneda:** el precio se convierte de la unidad del proveedor a la del producto (de
   una caja de 12 a una unidad, por ejemplo) y de la moneda del proveedor a la de la compañía.
6. **Redondeo:** a la precisión de "Precio de producto".

En el caso más común (precio con bonificación e IVA no incluido) da **precio × (1 − bonificación)**.

Antes de escribir nada hay una **vista previa**: costo actual, costo nuevo y variación de cada
producto y, si se elige una lista de precios, también el precio de venta actual y el nuevo. El
precio nuevo se calcula con el motor de listas de precios de Odoo, sin escribir el costo.

**Aplicar** escribe el costo en cada **variante**, en la compañía elegida y con los permisos del
usuario. Con Inventario instalado, Odoo registra cada cambio en su historial de costos ("Actualización
de precio de X a Y por usuario").

El módulo **no agrega campos ni vistas** a los precios de proveedor: solo la acción.

## Instalación

1. Agregar este repositorio, rama `19.0`, al `addons_path` de un servidor Odoo 19.
2. Instalar el módulo *Product Cost from Supplierinfo*. Depende solo de `purchase`.

Inventario (`stock_account`) y el punto de venta (`point_of_sale`) son opcionales: si están
instalados, el módulo los tiene en cuenta (historial de costos, métodos de costo y refresco de la
caja).

## Uso

La acción es solo para los **administradores de productos**. El menú *Actualizaciones de costo*
está en *Compras*, así que para verlo además hace falta acceso a Compras; el aviso que aparece al
aplicar trae un enlace a la actualización creada.

- **Desde los precios de proveedor** (*Compras > Configuración > Listas de precios de
  proveedores*): seleccionar las filas, con cualquier filtro, y usar *Acción > Tomar el costo del
  precio de proveedor*. Cada fila da el costo de su producto. Una fila sin variante vale para todas
  las variantes de la plantilla; una fila de una variante, solo para esa variante. Si el proveedor
  de la fila no es el **proveedor principal** del producto (el primero de la pestaña *Compra* con
  un precio vigente hoy), la línea queda marcada: así, aplicar la lista de un proveedor no cambia
  sin aviso el costo de los productos que se le compran a otro.
- **Desde los productos** (lista de productos o de variantes): seleccionar los productos y usar la
  misma acción. Toma el **proveedor principal** de cada producto, el que usa Odoo cuando repone
  sin un proveedor fijo: la primera fila válida de la pestaña *Compra* del producto (por
  secuencia) y, de ese proveedor, el precio más bajo para la *Cantidad de compra* (1 por defecto).
  No es el que usa una orden de compra: la orden usa siempre su propio proveedor. No se usan los
  precios cuyo mínimo supera la cantidad de compra.
- **Proveedores empatados:** si varios proveedores comparten el primer lugar (la misma
  secuencia), Odoo elige por el orden de la lista, que pone primero la cantidad mínima mayor y
  después el precio más bajo antes de la bonificación. La línea queda marcada, con los proveedores
  empatados, para que se defina el orden de los proveedores del producto. Desde los productos,
  también queda marcada cuando el primer proveedor del producto no tiene un precio vigente hoy para
  esa cantidad y se usa el de otro.

En la ventana:

- **Precio de venta en** (opcional): una lista de precios para ver el precio de venta actual y el
  nuevo de cada producto.
- **Marcar variaciones mayores a (%)**: 30 % por defecto. Los productos que lo superan quedan
  marcados y sin seleccionar, para revisarlos de a uno. Ahí caen, por ejemplo, los precios por caja
  cargados como si fueran por unidad.

La **vista previa** muestra una línea por producto con su acción (*Actualizar*, *Sin cambios* u
*Omitir*) y el motivo. Solo se aplican las líneas con *Aplicar* tildado; *Seleccionar todo*, *No
seleccionar ninguno* y *Quitar los marcados* ayudan a elegirlas.

- **Se omiten**, con el motivo: proveedor archivado, precio de otra compañía, precio en cero,
  producto archivado o de otra compañía, unidades de medida incompatibles, moneda sin tipo de
  cambio, costo FIFO o promedio (ese costo lo calcula Odoo), costo negativo y dos precios elegidos
  para el mismo producto. Desde los productos, también los que no tienen un precio de proveedor
  válido hoy para esa cantidad y esa compañía, con la razón: solo hay precios por cantidad mínima,
  solo hay proveedores archivados, ninguno vale hoy para la compañía o no hay ninguno.
- **Se marcan**, sin seleccionar: los precios que no están vigentes hoy, las variaciones mayores
  al umbral, los precios de un proveedor que no es el principal, los proveedores empatados en el
  primer lugar y, desde los productos, el primer proveedor sin precio vigente hoy.
- **Se informa**: si no había costo, si el precio es por una cantidad mínima, las conversiones de
  unidad y de moneda, los impuestos quitados o sumados, y si el precio de venta no depende del
  costo.

**Aplicar** vuelve a leer el costo y el método de costo de cada producto. Si el costo cambió
después de la vista previa (otro usuario, una recepción) o el producto pasó a costo FIFO o
promedio, lo deja como está y lo informa en la línea. Los productos que ya tienen el costo nuevo
(por ejemplo, porque se aplicó desde otra ventana) no se vuelven a escribir y se cuentan aparte en
el aviso. Si se aprieta *Aplicar* otra vez en la misma ventana, avisa que esa vista previa ya se
aplicó, con un enlace a la actualización, y no toca nada. Por eso se puede reintentar sin riesgo.

## Punto de venta

La caja guarda sus datos en el navegador y después solo recarga, en parte, las plantillas de
producto que cambiaron: un costo escrito en la variante **no llega** a una caja que ya tiene datos,
ni en esa sesión ni en las siguientes.

Por eso, cuando alguno de los productos actualizados se vende en la caja, el módulo mueve el campo
`last_data_change` de las cajas cuyos precios dependen del costo. Es lo mismo que hace Odoo cuando
se cambia la configuración de la caja. Revertir una actualización hace lo mismo.

- **Qué cajas.** Las de la compañía de la actualización que aplican una lista de precios con alguna
  regla basada en el costo, o una lista basada en otra que depende del costo (hasta 10 niveles):
  como lista predeterminada o disponible, solo si la caja usa listas de precios flexibles (sin esa
  opción la caja ignora su lista predeterminada y vende al precio de venta del producto); o a
  través de un *preset*, solo si la caja usa *presets*. También las cajas archivadas, que conservan
  sus datos en el navegador y los vuelven a usar si se restauran. Las demás cajas no se recargan:
  sus precios no cambian, pero la información del producto (costo y margen) sigue mostrando el
  costo anterior hasta que la caja vuelva a cargar sus datos por otro motivo.
- **Cuándo.** Después de confirmar los cambios y con un cursor propio, una sola vez por operación,
  para que una carga de la caja que empiece durante la aplicación no quede con datos viejos. Si otra
  transacción actualiza las mismas cajas al mismo tiempo, se reintenta hasta 3 veces; si igual
  falla, queda en el registro del servidor. No pasa por la escritura de la configuración de la caja,
  que puede instalar módulos y cambiar grupos.
- **Qué pasa en la caja.** En el navegador de cada caja, la próxima vez que se abre desde el tablero
  del Punto de venta, o cuando empieza una sesión nueva, la caja vuelve a cargar todos sus datos y
  **borra todos los pedidos que todavía no se enviaron al servidor**: el pedido en curso, los
  pedidos abiertos que no se guardaron para después (con el botón de subir del pedido) y los pedidos
  cobrados que no se pudieron enviar. Para tomar los costos nuevos, y los precios basados en ellos,
  hay que terminar o guardar esos pedidos y recién después abrir la caja otra vez desde el tablero.
  **Refrescar la página (F5) no recarga nada.**
- **Aviso.** La vista previa nombra las cajas activas de la compañía cuyos precios dependen del
  costo y que tienen una sesión abierta, cuando alguno de los productos que se van a actualizar se
  vende en la caja, y explica lo anterior.

**Alternativas evaluadas y no implementadas** (quedan para decidir):

- **Que la caja tome el costo nuevo con su carga parcial, sin recarga completa.** Después de
  confirmar, el módulo marcaría como modificadas (fecha de última modificación) las plantillas y
  las variantes actualizadas. La carga parcial que hace la caja al abrirse desde el tablero, o en
  una sesión nueva, trae las plantillas modificadas con sus variantes, y el navegador reemplaza sus
  datos por los nuevos sin borrar ningún pedido. Con los costos se puede, a diferencia de las reglas
  de las listas, porque un costo no se borra ni depende del orden. La parte del servidor se puede
  probar con `load_data`; falta comprobar la caja en el navegador. Como efecto secundario, cambia la
  fecha de última modificación de esos productos.
- **Postergar la recarga hasta que no haya sesiones abiertas.** Cuidaría los pedidos guardados en
  el navegador, pero los costos nuevos no entrarían durante el día, y necesitaría engancharse en la
  sesión de la caja para no competir con un cambio de turno.

## Historial y deshacer

Cada aplicación queda registrada en **Compras > Productos > Actualizaciones de costo** (hace falta
acceso a Compras para ver ese menú; el aviso que aparece al aplicar también trae un enlace a la
actualización): quién, cuándo, la compañía, de dónde salió (precios elegidos o proveedor principal)
y, por producto, el proveedor, el costo anterior y el nuevo. Para los administradores de productos
el historial es de solo lectura: lo escribe solo el módulo.

**Revertir** devuelve el costo anterior a los productos que **siguen con el costo de esa
actualización**, que **ninguna actualización posterior volvió a cambiar** y que siguen con costo
estándar. Los demás quedan como están, con una nota: "Costo modificado después de este cambio",
"Cambiado por una actualización de costo posterior" o "El método de costo es FIFO o promedio".
Para deshacer una actualización que tiene otras posteriores sobre los mismos productos, primero hay
que revertir las posteriores, de la más nueva a la más vieja.

Al terminar, un aviso dice cuántos productos se revirtieron y cuántos quedaron como estaban. Si se
revirtió al menos uno, el estado pasa a *Revertido* (todos) o a *Revertido en parte*; si no se pudo
revertir ninguno, el aviso es de advertencia y el estado no cambia. Si más tarde un producto vuelve
al costo de la actualización, se puede revertir de nuevo. Revertir dos veces no cambia nada.

## Limitaciones conocidas

- El costo es el de una unidad comprada hoy. Los impuestos de monto fijo también son por unidad,
  así que no cambian el costo de una compra de varias unidades; en esa compra solo puede variar el
  redondeo a centavos de la parte no deducible de los impuestos.
- El precio del proveedor se redondea como en una orden de compra hecha en la moneda del proveedor.
  Si la orden se hace en otra moneda, Odoo redondea después de convertir, y el costo puede diferir
  en el último decimal del de esa recepción.
- Los productos con costo FIFO o promedio se omiten: ese costo lo calcula Odoo con las recepciones.
- **Tiempo de espera:** con Inventario, cada costo que cambia pasa por la revaloración de Odoo
  (historial de costos y movimientos de stock pendientes de valorar), así que aplicar miles de
  costos distintos lleva tiempo. Detrás de un proxy que corta a los 60 segundos, un catálogo entero
  puede dar error 504 aunque Odoo termine de grabar. Conviene aplicar por proveedor o por marca;
  reintentar es seguro: lo que ya tiene el costo nuevo no se vuelve a escribir.
- **Caja:** los costos nuevos llegan cuando la caja se abre de nuevo desde el tablero o en una
  sesión nueva, y solo se recargan las cajas cuyos precios dependen del costo. Esa recarga es
  completa y borra en ese navegador los pedidos que no se enviaron al servidor: el pedido en curso,
  los pedidos abiertos que no se guardaron para después y los pedidos cobrados que no se pudieron
  enviar.
- **Desinstalar** el módulo borra las actualizaciones de costo registradas. El historial de costos
  de Odoo se conserva.

## Pruebas

El módulo incluye 91 tests automáticos, que corren como un administrador de productos con acceso a
Compras (no como superusuario). Cubren el costo neto (bonificación, impuestos incluidos, excluidos
y no deducibles, posición fiscal, caja de 12, moneda y redondeo), comparado con
`_get_stock_move_price_unit`, la función con la que Odoo valora la recepción de una línea de orden
de compra, en siete casos (fila simple, impuesto incluido, caja de 12, precio en EUR, impuesto en
parte no deducible, posición fiscal y precio con tres decimales y bonificación); cada motivo de
omisión y de marca, filas de plantilla y de variante, el proveedor principal, los empates y los
escalones por cantidad, el precio de venta de la vista previa contra el real, la ausencia de
efectos de la vista previa, el asistente abierto como lo abre el navegador, aplicar dos veces,
permisos (también que cada usuario ve solo sus vistas previas y que el historial es de solo
lectura), revertir (completo, en parte, dos veces, con actualizaciones posteriores y con costo
FIFO), multicompañía y el refresco de la caja: qué cajas se recargan (listas basadas en el costo,
directa o indirectamente, *presets*, cajas sin listas de precios, archivadas y de otra compañía),
que se haga después de confirmar y sin escribir la configuración, y los reintentos. Los que
necesitan `stock_account`, `purchase_stock` o `point_of_sale` se saltean si esos módulos no están
instalados. Para correrlos:

```
odoo -d <base_de_prueba> -i product_cost_from_supplierinfo --test-enable \
     --test-tags /product_cost_from_supplierinfo --stop-after-init
```

## Créditos

- Autores: Renzo Payero y DakoDev.

La ficha del módulo, la que muestra Odoo en Aplicaciones, está en
[product_cost_from_supplierinfo/README.rst](product_cost_from_supplierinfo/README.rst).

## Licencia

[AGPL-3.0 o posterior](LICENSE).
