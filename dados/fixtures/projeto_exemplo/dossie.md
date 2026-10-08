# PROJETO DE EXEMPLO PRJ-TESTE (FICTICIO)

Dados totalmente inventados para teste. Nao representam nenhum projeto real.

## Problema

Uma interrupcao fazia a mesma confirmacao chegar duas vezes ao conciliador, gerando divergencias no registro de eventos.

## Estado anterior

O barramento ja possuia mecanismo de idempotencia por identificador de mensagem. A equipe apenas ajustou parametros de tempo limite.

## Hipotese e resultado

Testou-se se um identificador composto, combinando origem e sequencia, permitia distinguir reenvios legitimos de duplicatas sem bloquear pagamentos validos.
