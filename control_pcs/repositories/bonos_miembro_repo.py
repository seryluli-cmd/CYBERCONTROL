"""
bonos_miembro_repo.py
=======================
Catálogo de bonos de tiempo EXCLUSIVO para Miembros (socios con saldo
prepago) -- separado a propósito de pcs_repo.bonos_tiempo, que es el
catálogo de bonos COMUNES para cualquier persona que entra al local sin
ser socia. Lo usa "Cargar Saldo" -> "Bono fijo" (ver
control_pcs/ui/miembros_window.py). El dueño pidió separar los catálogos
porque a los socios les conviene ofrecerles combos propios.

Mismo esquema y mismas reglas que bonos_tiempo (nombre/minutos/precio,
"activo" para dar de baja sin romper el historial de cargas que ya lo
usaron) -- la única diferencia real es la tabla. Crear/editar/dar de baja
un bono, acá y en pcs_repo.crear_bono/modificar_bono/desactivar_bono por
igual, es exclusivo de ADMIN (ver ui/main_window.ConfiguracionAdminWindow)
-- cualquiera con 'permiso_control_pcs' puede seguir usando un bono ya
creado (asignarlo, cargarlo), no editar el catálogo. Esa restricción se
aplica en la UI (qué botón se muestra), no acá: este repo no sabe nada de
permisos, igual que el resto de repositories/ (ver CLAUDE.md, regla 1).
"""

from control_pcs.repositories.catalogo_bonos import CatalogoDeBonos

# La mecánica (listar, crear, ...) es la de CatalogoDeBonos sobre la tabla
# bonos_miembro. Un bono dado de baja (desactivar_bono) no se borra: un bono
# ya cargado por algún socio queda referenciado desde
# movimientos_saldo_miembro, y solo deja de ofrecerse para cargas nuevas.
_catalogo_bonos = CatalogoDeBonos("bonos_miembro")
listar_bonos = _catalogo_bonos.listar
obtener_bono = _catalogo_bonos.obtener
crear_bono = _catalogo_bonos.crear
modificar_bono = _catalogo_bonos.modificar
desactivar_bono = _catalogo_bonos.desactivar
