"""Política de retención del histórico.

Se limpia cuando se cumple cualquiera de estas condiciones:
- la noticia más antigua almacenada supera los 14 días, o
- el total de noticias supera las 200 (recortando primero las más antiguas).
"""
