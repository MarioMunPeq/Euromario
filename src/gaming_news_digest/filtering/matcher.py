"""Matcher robusto de nombres de juegos para el filtro de inclusión/exclusión.

Principios: límites de palabra (nada de matches por subcadena casual),
soporte de aliases y variantes de secuelas, insensibilidad a
mayúsculas/acentos. La exclusión siempre tiene prioridad sobre la inclusión.
"""
