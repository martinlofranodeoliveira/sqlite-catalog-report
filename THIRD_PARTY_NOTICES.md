# Componentes e avisos de terceiros

O código e a documentação deste projeto são distribuídos sob a [licença MIT](LICENSE). O pacote não incorpora nem distribui cópias do Python, do SQLite ou de bibliotecas externas. Não há dependências de execução externas à biblioteca padrão do Python.

## Código adaptado de wheel-record-audit

O publicador de arquivos novos em `cli._publish_new` e a verificação em `scripts/check_public_tree.py` incluem adaptações de código do projeto [wheel-record-audit](https://github.com/martinlofranodeoliveira/wheel-record-audit), também distribuído sob licença MIT.

Copyright (c) 2026 Contribuidores da LOFRANO TECNOLOGIA. O aviso e os termos MIT aplicáveis estão preservados em [LICENSE](LICENSE).

## Python e módulo sqlite3

A aplicação utiliza o runtime Python instalado pelo usuário e seu módulo padrão `sqlite3`. O Python tem termos de licença próprios, descritos em [History and License](https://docs.python.org/3/license.html). A licença MIT deste repositório não substitui esses termos nem relicencia o runtime.

## SQLite

O módulo `sqlite3` utiliza a biblioteca SQLite disponível na distribuição do Python ou no sistema do usuário. O projeto SQLite declara seu código em domínio público; consulte a [declaração oficial de copyright](https://www.sqlite.org/copyright.html).

A versão efetiva do SQLite depende desse ambiente, não da versão do pacote. Verifique-a com:

```bash
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Este repositório não inclui uma cópia vendorizada do SQLite. Termos de outros componentes eventualmente incluídos pelo fornecedor do seu Python ou sistema operacional devem ser consultados na respectiva distribuição.

## Ferramentas de desenvolvimento

`build` e `setuptools` são ferramentas de construção e desenvolvimento, com versões declaradas no `pyproject.toml`. Elas não integram o código distribuído do runtime desta aplicação e mantêm suas próprias licenças: [build](https://github.com/pypa/build) e [setuptools](https://github.com/pypa/setuptools).
