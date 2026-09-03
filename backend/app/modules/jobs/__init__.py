"""Ledger durable de jobs e idempotencia. Redis (`app.jobs`) sigue siendo el transporte.

No debe hacer: ejecutar workers ni implementar lógica de dominio de cada cola.
Ref: diseño 6.1, 8.1, 3.BE.14.
"""
