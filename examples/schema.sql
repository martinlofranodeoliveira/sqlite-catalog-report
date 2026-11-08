-- Esquema inteiramente sintético; os relatórios não exportam seus registros.
PRAGMA user_version = 1;
CREATE TABLE categorias (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE
) STRICT;
CREATE TABLE produtos (
    sku TEXT PRIMARY KEY,
    categoria_id INTEGER REFERENCES categorias,
    nome TEXT NOT NULL,
    preco_centavos INTEGER NOT NULL CHECK(preco_centavos >= 0),
    nome_busca TEXT GENERATED ALWAYS AS (lower(nome)) VIRTUAL,
    preco_dobrado INTEGER GENERATED ALWAYS AS (preco_centavos * 2) STORED
) WITHOUT ROWID;
CREATE INDEX produtos_nome_parcial ON produtos(lower(nome)) WHERE preco_centavos > 0;
CREATE UNIQUE INDEX produtos_categoria_nome ON produtos(categoria_id, nome COLLATE NOCASE DESC);
CREATE TABLE pedidos (
    id INTEGER PRIMARY KEY,
    produto_sku TEXT NOT NULL REFERENCES produtos(sku) ON UPDATE CASCADE,
    quantidade INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE TABLE equipes (
    id INTEGER PRIMARY KEY,
    gestor_id INTEGER REFERENCES gestores(id)
);
CREATE TABLE gestores (
    id INTEGER PRIMARY KEY,
    equipe_id INTEGER REFERENCES equipes(id)
);
CREATE TABLE eventos (
    id INTEGER PRIMARY KEY,
    mensagem TEXT DEFAULT 'PADRAO_FICTICIO'
);
CREATE VIEW vitrine AS
    SELECT p.sku, p.nome, c.nome AS categoria
    FROM produtos AS p JOIN categorias AS c ON c.id = p.categoria_id;
CREATE TRIGGER produto_aviso AFTER UPDATE ON produtos
    BEGIN INSERT INTO eventos(mensagem) VALUES ('ALTERACAO_FICTICIA'); END;
INSERT INTO categorias(id, nome) VALUES (1, 'REGISTRO_FICTICIO_NAO_EXPORTAR');
INSERT INTO produtos(sku, categoria_id, nome, preco_centavos)
    VALUES ('SKU_EXEMPLO', 1, 'REGISTRO_FICTICIO_NAO_EXPORTAR', 500);
