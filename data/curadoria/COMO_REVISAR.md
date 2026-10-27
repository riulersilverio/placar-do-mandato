# Como revisar as promessas

Cada planilha desta pasta lista compromissos concretos tirados de um plano de governo registrado no TSE.
As linhas começam como **sugestão** (`revisado = não`) e só aparecem no site público depois de revisadas.

## Passo a passo

1. Abra a planilha no Excel (separador `;`, codificação UTF-8).
2. Para cada linha, confira:
   - **compromisso**: resume bem o `trecho_original` do plano, sem exagerar nem suavizar?
   - **status_sugerido**: está correto com base na `evidencia`? Abra o link.
   - Linhas com "Revisor:" na justificativa pedem uma checagem específica.
3. Se concordar, escreva `sim` na coluna **revisado**.
4. Se discordar do status, escreva o status correto em **status_final** (ele substitui o sugerido) e explique em
   **observacao_revisor**. Use só: `Cumprida`, `Cumprida em parte`, `Em andamento`, `Não cumprida`, `Não iniciada`.
5. Se o compromisso não fizer sentido, apague a linha.
6. Salve mantendo o formato CSV.

## Ver as sugestões no app antes de publicar

No PowerShell, dentro da pasta do projeto:

```powershell
$env:PLACAR_REVISAO = "1"; streamlit run app.py
```

Sem essa variável, o app mostra só o que tem `revisado = sim`.

## Critérios

- **Cumprida**: o compromisso foi feito (lei aprovada, programa criado, decisão tomada).
- **Cumprida em parte**: parte foi feita, ou foi feito de forma diferente da prometida.
- **Em andamento**: há ação concreta (projeto enviado, programa lançado), mas sem resultado final.
- **Não cumprida**: não foi feito até a data da verificação.
- **Não iniciada**: o mandato ainda não começou (governadores eleitos em 2026, posse em 06/01/2027).

Diretrizes genéricas ("fortalecer a democracia") ficam de fora, porque não dá para verificar.
