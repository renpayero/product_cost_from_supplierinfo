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
