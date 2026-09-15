"""Contratos de entrada e saída da API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Motivo(BaseModel):
    feature: str
    descricao: str
    valor: float
    contribuicao: float = Field(description="> 0 empurra o cartão para a anomalia")


class ScoreResponse(BaseModel):
    card_id: str | None = None
    anomaly_score: float = Field(description="maior = mais suspeito")
    percentil: float = Field(description="posição do score na população de treino (0-1)")
    alerta: bool = Field(description="score acima do limiar da fila de auditoria")
    limiar: float
    motivos: list[Motivo] = []
    modelo: str


class FeaturesRequest(BaseModel):
    card_id: str | None = None
    features: dict[str, float] = Field(description="features de gold/card_features; ausentes = 0")


class Validacao(BaseModel):
    """Uma linha do 'EXTRATO DE USO' (embarque ou recarga)."""
    event_ts: datetime
    tipo: Literal["USADO", "REC"]
    status_emb: Literal["NORMAL", "ERRO DE LEITURA", "ERRO DE GRAVAÇÃO", "SALDO INSUFICIENTE"] = "NORMAL"
    descricao: str = Field(examples=["VANGUARDA 457 003 V", "Recarga Aurora Moda - Pedido 123456"])
    cart_a: float = Field(ge=0)
    cart_b: float = Field(ge=0)
    dc: Literal["D", "C"] | None = None
    vd: float = Field(gt=0)


class TransacoesRequest(BaseModel):
    card_id: str
    transacoes: list[Validacao] = Field(min_length=2)


class CardScore(BaseModel):
    card_id: str
    nome: str | None
    anomaly_score: float
    percentil: float
    alerta: bool
    rank: int
    cluster: int
    motivo_principal: str | None = None


class Health(BaseModel):
    status: Literal["ok", "degradado"]
    modelo_carregado: bool
    versao_modelo: str | None
    cartoes_pontuados: int
