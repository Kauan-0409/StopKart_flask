from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, join_room, emit, disconnect
import random
import string
import json
import unicodedata
import re
import time

app = Flask(__name__)

app.config["SECRET_KEY"] = "stop-carro-secret"

socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*"
)

# ==========================================
# CONFIGURAÇÕES PADRÃO
# ==========================================

TEMPO_PADRAO = 120
INTERVALO_RODADAS = 120
MAX_JOGADORES_PADRAO = 2
RODADAS_PADRAO = 6
VIDAS_INICIAIS = 3

MIN_RODADAS = 1
MAX_RODADAS = 50

LETRAS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


# ==========================================
# CARROS
# ==========================================

with open("cars.json", "r", encoding="utf-8") as f:
    carros = json.load(f)


def normalizar_carro(nome):
    nome = unicodedata.normalize(
        "NFD",
        str(nome).strip().lower()
    )

    nome = "".join(
        c for c in nome
        if unicodedata.category(c) != "Mn"
    )

    return re.sub(r"[^a-z0-9]", "", nome)


carros_normalizados = {
    normalizar_carro(c): c
    for c in carros
}


# ==========================================
# SALAS / CONEXÕES
# ==========================================

salas = {}

# sid -> {"codigo": codigo, "nome": nome}
conexoes = {}


# ==========================================
# GERAR CÓDIGO
# ==========================================

def gerar_codigo():

    while True:

        codigo = "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=6
            )
        )

        if codigo not in salas:
            return codigo


# ==========================================
# ESTADO DOS JOGADORES
# ==========================================

def estado_jogadores(sala):

    jogadores = []

    for nome in sala["jogadores"]:

        vidas = sala["vidas"].get(
            nome,
            VIDAS_INICIAIS
        )

        jogadores.append({
            "nome": nome,
            "vidas": vidas,
            "eliminado": vidas <= 0,
            "host": nome == sala["host"],
            "pontos": sala["pontos"].get(nome, 0)
        })

    return jogadores


# ==========================================
# RANKING
# ==========================================

def gerar_ranking(sala):

    jogadores = []

    for nome in sala["jogadores"]:

        vidas = sala["vidas"].get(
            nome,
            0
        )

        pontos = sala["pontos"].get(
            nome,
            0
        )

        respostas = sala["respostas_validas"].get(
            nome,
            0
        )

        jogadores.append({
            "nome": nome,
            "vidas": vidas,
            "pontos": pontos,
            "respostas": respostas,
            "eliminado": vidas <= 0
        })

    # ======================================
    # ORDEM DO RANKING
    #
    # 1º pontos
    # 2º vidas
    # 3º respostas corretas
    # ======================================

    jogadores.sort(
        key=lambda jogador: (
            jogador["pontos"],
            jogador["vidas"],
            jogador["respostas"]
        ),
        reverse=True
    )

    # ======================================
    # POSIÇÕES
    # ======================================

    ranking = []

    for posicao, jogador in enumerate(
        jogadores,
        start=1
    ):

        jogador["posicao"] = posicao

        ranking.append(jogador)

    return ranking


# ==========================================
# ATUALIZAR LOBBY
# ==========================================

def atualizar_lobby(codigo):

    if codigo not in salas:
        return

    sala = salas[codigo]

    socketio.emit(
        "atualizar_jogadores",
        {
            "jogadores": estado_jogadores(sala),
            "max_jogadores": sala["max_jogadores"],
            "tempo": sala["tempo_rodada"],
            "total_rodadas": sala["total_rodadas"],
            "rodada": sala["rodada"],
            "jogo_iniciado": sala["jogo_iniciado"],
            "em_intervalo": sala["em_intervalo"],
            "intervalo_habilitado": sala["intervalo_habilitado"],
            "intervalo_duracao": INTERVALO_RODADAS,
            "modo": sala["modo"]
        },
        to=codigo
    )


# ==========================================
# DADOS DA SALA
# ==========================================

def dados_sala(codigo):

    sala = salas[codigo]

    return {
        "jogadores": estado_jogadores(sala),
        "max_jogadores": sala["max_jogadores"],
        "tempo": sala["tempo_rodada"],
        "total_rodadas": sala["total_rodadas"],
        "jogo_iniciado": sala["jogo_iniciado"],
        "rodada": sala["rodada"],
        "letra": sala["letra"],
        "fim": sala["fim_rodada"],
        "em_intervalo": sala["em_intervalo"],
        "fim_intervalo": sala["fim_intervalo"],
        "modo": sala["modo"],
        "intervalo_habilitado": sala["intervalo_habilitado"],
        "intervalo_duracao": INTERVALO_RODADAS
    }


# ==========================================
# PÁGINA INICIAL
# ==========================================

@app.route("/")
def inicio():

    return render_template("index.html")


# ==========================================
# CRIAR SALA
# ==========================================

@app.route("/criar", methods=["POST"])
def criar_sala():

    nome = request.form.get(
        "nome",
        ""
    ).strip()

    if not re.fullmatch(
        r"[A-Za-z0-9_]+",
        nome
    ):

        return (
            "nome inválido! "
            "use apenas letras, números e _ 😭"
        )

    # ======================================
    # MODO
    # ======================================

    modo = request.form.get(
        "modo",
        "multi"
    )

    # ======================================
    # INTERVALO
    # ======================================

    intervalo_habilitado = (
        request.form.get(
            "intervalo_habilitado",
            "1"
        ) == "1"
    )

    # Solo nunca usa intervalo
    if modo == "solo":
        intervalo_habilitado = False

    # ======================================
    # TEMPO
    # ======================================

    try:

        tempo = int(
            request.form.get(
                "tempo",
                TEMPO_PADRAO
            )
        )

    except:

        tempo = TEMPO_PADRAO

    # ======================================
    # RODADAS
    # ======================================

    try:

        total_rodadas = int(
            request.form.get(
                "total_rodadas",
                RODADAS_PADRAO
            )
        )

    except:

        total_rodadas = RODADAS_PADRAO

    # ======================================
    # JOGADORES
    # ======================================

    try:

        max_jogadores = int(
            request.form.get(
                "max_jogadores",
                MAX_JOGADORES_PADRAO
            )
        )

    except:

        max_jogadores = MAX_JOGADORES_PADRAO

    # ======================================
    # LIMITES
    # ======================================

    tempo = max(
        30,
        min(600, tempo)
    )

    total_rodadas = max(
        MIN_RODADAS,
        min(MAX_RODADAS, total_rodadas)
    )

    # ======================================
    # MODO SOLO
    # ======================================

    if modo == "solo":

        max_jogadores = 1

    else:

        max_jogadores = max(
            2,
            min(20, max_jogadores)
        )

    # ======================================
    # LETRAS REMOVIDAS
    # ======================================

    removidas = [
        x.upper()
        for x in request.form.getlist(
            "letras_removidas"
        )
        if x.upper() in LETRAS
    ]

    # ======================================
    # CÓDIGO
    # ======================================

    codigo = gerar_codigo()

    # ======================================
    # CRIAR SALA
    # ======================================

    salas[codigo] = {

        "host": nome,

        "jogadores": [
            nome
        ],

        "max_jogadores":
            max_jogadores,

        "tempo_rodada":
            tempo,

        "total_rodadas":
            total_rodadas,

        "modo":
            modo,

        "letras_removidas":
            removidas,

        "letra":
            None,

        "jogo_iniciado":
            False,

        "rodada":
            0,

        "vidas": {
            nome:
                VIDAS_INICIAIS
        },

        "pontos": {
            nome:
                0
        },

        "respostas_validas": {
            nome:
                0
        },

        "carros_usados":
            [],

        "responderam":
            set(),

        "fim_rodada":
            None,

        "timer_ativo":
            False,

        "encerrando_rodada":
            False,

        # ==================================
        # INTERVALO ENTRE RODADAS
        # ==================================

        "em_intervalo":
            False,

        "fim_intervalo":
            None,

        "intervalo_habilitado":
            intervalo_habilitado
    }

    return redirect(
        url_for(
            "sala",
            codigo=codigo,
            nome=nome
        )
    )


# ==========================================
# ENTRAR NA SALA
# ==========================================

@app.route("/entrar", methods=["POST"])
def entrar_sala():

    nome = request.form.get(
        "nome",
        ""
    ).strip()

    codigo = request.form.get(
        "codigo",
        ""
    ).upper().strip()

    if not re.fullmatch(
        r"[A-Za-z0-9_]+",
        nome
    ):

        return (
            "nome inválido! "
            "use apenas letras, números e _ 😭"
        )

    if codigo not in salas:

        return "sala não encontrada 😭"

    sala = salas[codigo]

    if sala["jogo_iniciado"]:

        return (
            "essa partida já começou 😭"
        )

    if len(sala["jogadores"]) >= sala["max_jogadores"]:

        return (
            "essa sala está cheia 😭"
        )

    if nome in sala["jogadores"]:

        return (
            "esse nome já está na sala 😭"
        )

    sala["jogadores"].append(nome)

    sala["vidas"][nome] = VIDAS_INICIAIS

    sala["pontos"][nome] = 0

    sala["respostas_validas"][nome] = 0

    return redirect(
        url_for(
            "sala",
            codigo=codigo,
            nome=nome
        )
    )


# ==========================================
# PÁGINA DA SALA
# ==========================================

@app.route("/sala/<codigo>")
def sala(codigo):

    if codigo not in salas:

        return "sala não encontrada 😭"

    sala_data = salas[codigo]

    nome = request.args.get(
        "nome",
        ""
    ).strip()

    if nome not in sala_data["jogadores"]:

        return (
            "jogador não pertence "
            "a esta sala 😭"
        )

    return render_template(
        "salas.html",

        codigo=codigo,

        nome=nome,

        host=sala_data["host"],

        jogadores=estado_jogadores(
            sala_data
        ),

        jogo_iniciado=
            sala_data["jogo_iniciado"],

        tempo=
            sala_data["tempo_rodada"],

        max_jogadores=
            sala_data["max_jogadores"],

        total_rodadas=
            sala_data["total_rodadas"],

        modo=
            sala_data["modo"],

        em_intervalo=
            sala_data["em_intervalo"],

        intervalo_habilitado=
            sala_data["intervalo_habilitado"]
    )


# ==========================================
# SOCKET CONNECT
# ==========================================

@socketio.on("connect")
def conectado():

    emit(
        "conexao_status",
        {
            "conectado": True
        }
    )


# ==========================================
# ENTRAR NO SOCKET DA SALA
# ==========================================

@socketio.on("entrar_sala")
def entrar_sala_socket(data):

    codigo = str(
        data.get(
            "codigo",
            ""
        )
    ).upper().strip()

    nome = str(
        data.get(
            "nome",
            ""
        )
    ).strip()

    if codigo not in salas:

        emit(
            "erro_socket",
            {
                "mensagem":
                    "sala não encontrada"
            }
        )

        return

    sala = salas[codigo]

    if nome not in sala["jogadores"]:

        emit(
            "erro_socket",
            {
                "mensagem":
                    "jogador não pertence à sala"
            }
        )

        return

    conexoes[request.sid] = {
        "codigo": codigo,
        "nome": nome
    }

    join_room(codigo)

    emit(
        "sala_pronta",
        dados_sala(codigo)
    )

    atualizar_lobby(codigo)

    # ======================================
    # SINCRONIZAÇÃO DA RODADA
    # ======================================

    if (
        sala["jogo_iniciado"]
        and not sala["em_intervalo"]
        and sala["letra"]
        and sala["fim_rodada"]
    ):

        restante = max(
            0,
            int(
                sala["fim_rodada"]
                - time.time()
            )
        )

        emit(
            "nova_rodada",
            {
                "rodada":
                    sala["rodada"],

                "total_rodadas":
                    sala["total_rodadas"],

                "letra":
                    sala["letra"],

                "tempo":
                    restante,

                "fim":
                    sala["fim_rodada"]
            }
        )

    # ======================================
    # SINCRONIZAÇÃO DO INTERVALO
    # ======================================

    elif (
        sala["jogo_iniciado"]
        and sala["em_intervalo"]
        and sala["fim_intervalo"]
    ):

        restante = max(
            0,
            int(
                sala["fim_intervalo"]
                - time.time()
            )
        )

        emit(
            "intervalo_iniciado",
            {
                "rodada":
                    sala["rodada"],

                "proxima_rodada":
                    sala["rodada"] + 1,

                "tempo":
                    restante,

                "fim":
                    sala["fim_intervalo"]
            }
        )


# ==========================================
# JOGADOR ATUAL
# ==========================================

def jogador_atual():

    conexao = conexoes.get(
        request.sid
    )

    if not conexao:
        return None, None, None

    codigo = conexao["codigo"]

    nome = conexao["nome"]

    if codigo not in salas:
        return None, None, None

    return (
        codigo,
        nome,
        salas[codigo]
    )


# ==========================================
# COMEÇAR JOGO
# ==========================================

@socketio.on("comecar_jogo")
def comecar_jogo():

    codigo, nome, sala = jogador_atual()

    if not sala:

        emit(
            "erro_socket",
            {
                "mensagem":
                    "conecte-se à sala primeiro"
            }
        )

        return

    if nome != sala["host"]:

        emit(
            "erro_socket",
            {
                "mensagem":
                    "somente o host pode iniciar"
            }
        )

        return

    if sala["jogo_iniciado"]:
        return

    # ======================================
    # SALA PRECISA ESTAR CHEIA
    # ======================================

    quantidade_jogadores = len(sala["jogadores"])
    max_jogadores = sala["max_jogadores"]

    if quantidade_jogadores < max_jogadores:
        emit(
            "erro_socket",
            {
                "mensagem":
                    f"aguarde todos os jogadores entrarem "
                    f"({quantidade_jogadores}/{max_jogadores})"
            }
        )
        return

    # ======================================
    # RESET DA PARTIDA
    # ======================================

    sala["jogo_iniciado"] = True

    sala["rodada"] = 1

    sala["carros_usados"] = []

    sala["responderam"] = set()

    sala["encerrando_rodada"] = False

    sala["em_intervalo"] = False

    sala["fim_intervalo"] = None

    sala["fim_rodada"] = None

    sala["timer_ativo"] = False

    for jogador in sala["jogadores"]:

        sala["vidas"][jogador] = VIDAS_INICIAIS

        sala["pontos"][jogador] = 0

        sala["respostas_validas"][jogador] = 0

    # ======================================
    # PRIMEIRA RODADA
    # SEM INTERVALO
    # ======================================

    iniciar_rodada(codigo)

@socketio.on("expulsar_jogador")
def expulsar_jogador(data):
    codigo, nome, sala = jogador_atual()

    if not sala:
        emit("erro_socket", {
            "mensagem": "conecte-se à sala primeiro"
        })
        return

    # somente o host pode expulsar
    if nome != sala["host"]:
        emit("erro_socket", {
            "mensagem": "somente o host pode expulsar jogadores"
        })
        return

    jogador_expulso = str(data.get("nome", "")).strip()

    if not jogador_expulso:
        emit("erro_socket", {
            "mensagem": "jogador inválido"
        })
        return

    # o host não pode se expulsar
    if jogador_expulso == sala["host"]:
        emit("erro_socket", {
            "mensagem": "o host não pode ser expulso"
        })
        return

    # verifica se o jogador realmente está na sala
    if jogador_expulso not in sala["jogadores"]:
        emit("erro_socket", {
            "mensagem": "esse jogador não está na sala"
        })
        return

    # remove o jogador da sala
    sala["jogadores"].remove(jogador_expulso)

    # limpa os dados dele
    sala["vidas"].pop(jogador_expulso, None)

    # procura a conexão/socket do jogador expulso
    sid_expulso = None

    for sid, conexao in list(conexoes.items()):
        if (
            conexao.get("codigo") == codigo
            and conexao.get("nome") == jogador_expulso
        ):
            sid_expulso = sid
            break

    # avisa o jogador antes de desconectar
    if sid_expulso:
        socketio.emit(
            "voce_foi_expulso",
            {
                "mensagem": "você foi expulso da sala pelo host."
            },
            to=sid_expulso
        )

        # remove a conexão
        conexoes.pop(sid_expulso, None)

        # tira o jogador da room do Socket.IO
        try:
            from flask_socketio import leave_room
            socketio.server.leave_room(
                sid_expulso,
                codigo,
                namespace="/"
            )
        except Exception:
            pass

    # avisa os outros jogadores
    socketio.emit(
        "jogador_expulso",
        {
            "nome": jogador_expulso
        },
        to=codigo
    )

    # atualiza a lista para todo mundo
    atualizar_lobby(codigo)

# ==========================================
# INICIAR RODADA
# ==========================================

def iniciar_rodada(codigo):

    if codigo not in salas:
        return

    sala = salas[codigo]

    if not sala["jogo_iniciado"]:
        return

    # ======================================
    # VERIFICAR LIMITE DE RODADAS
    # ======================================

    if sala["rodada"] > sala["total_rodadas"]:

        finalizar_jogo(codigo)

        return

    # ======================================
    # ESCOLHER LETRA
    # ======================================

    disponiveis = [
        letra
        for letra in LETRAS
        if letra not in sala["letras_removidas"]
    ]

    if not disponiveis:

        finalizar_jogo(codigo)

        return

    # ======================================
    # LIMPAR ESTADO DA RODADA
    # ======================================

    sala["em_intervalo"] = False

    sala["fim_intervalo"] = None

    sala["letra"] = random.choice(
        disponiveis
    )

    sala["responderam"] = set()

    sala["encerrando_rodada"] = False

    # ======================================
    # INICIAR TIMER
    # ======================================

    sala["fim_rodada"] = (
        time.time()
        + sala["tempo_rodada"]
    )

    # ======================================
    # AVISAR CLIENTES
    # ======================================

    socketio.emit(
        "nova_rodada",
        {
            "rodada":
                sala["rodada"],

            "total_rodadas":
                sala["total_rodadas"],

            "letra":
                sala["letra"],

            "tempo":
                sala["tempo_rodada"],

            "fim":
                sala["fim_rodada"]
        },
        to=codigo
    )

    atualizar_lobby(codigo)

    # ======================================
    # INICIAR CRONÔMETRO
    # ======================================

    if not sala["timer_ativo"]:

        sala["timer_ativo"] = True

        socketio.start_background_task(
            controlar_tempo,
            codigo
        )


# ==========================================
# JOGADORES PENDENTES
# ==========================================

def jogadores_pendentes(sala):

    return [
        jogador

        for jogador in sala["jogadores"]

        if sala["vidas"].get(
            jogador,
            0
        ) > 0

        and jogador not in sala["responderam"]
    ]


# ==========================================
# TODOS RESPONDERAM
# ==========================================

def todos_responderam(codigo):

    if codigo not in salas:
        return False

    sala = salas[codigo]

    vivos = [
        jogador
        for jogador in sala["jogadores"]
        if sala["vidas"].get(
            jogador,
            0
        ) > 0
    ]

    if not vivos:
        return True

    return all(
        jogador in sala["responderam"]
        for jogador in vivos
    )


# ==========================================
# CRONÔMETRO
# ==========================================

def controlar_tempo(codigo):

    while codigo in salas:

        sala = salas[codigo]

        if not sala["jogo_iniciado"]:

            sala["timer_ativo"] = False

            return

        # ==================================
        # INTERVALO
        # ==================================

        if sala["em_intervalo"]:

            if sala["fim_intervalo"] is None:

                socketio.sleep(0.5)

                continue

            restante = max(
                0,
                int(
                    sala["fim_intervalo"]
                    - time.time()
                )
            )

            socketio.emit(
                "tempo_intervalo_atualizado",
                {
                    "restante":
                        restante
                },
                to=codigo
            )

            if restante <= 0:

                iniciar_proxima_rodada(
                    codigo
                )

            socketio.sleep(1)

            continue

        # ==================================
        # RODADA NORMAL
        # ==================================

        if sala["fim_rodada"] is None:

            socketio.sleep(0.5)

            continue

        restante = max(
            0,
            int(
                sala["fim_rodada"]
                - time.time()
            )
        )

        socketio.emit(
            "tempo_atualizado",
            {
                "restante":
                    restante
            },
            to=codigo
        )

        if restante <= 0:

            terminar_rodada(
                codigo,
                por_tempo=True
            )

        socketio.sleep(1)


# ==========================================
# TERMINAR RODADA
# ==========================================

def terminar_rodada(
    codigo,
    por_tempo=False
):

    if codigo not in salas:
        return

    sala = salas[codigo]

    if sala["encerrando_rodada"]:
        return

    if not sala["jogo_iniciado"]:
        return

    if sala["em_intervalo"]:
        return

    sala["encerrando_rodada"] = True

    # ======================================
    # QUEM NÃO RESPONDEU PERDE VIDA
    # ======================================

    if por_tempo:

        pendentes = jogadores_pendentes(
            sala
        )

        for jogador in pendentes:

            sala["vidas"][jogador] -= 1

            if sala["vidas"][jogador] < 0:
                sala["vidas"][jogador] = 0

    # ======================================
    # ZERA TIMER
    # ======================================

    sala["fim_rodada"] = None

    socketio.emit(
        "tempo_atualizado",
        {
            "restante": 0
        },
        to=codigo
    )

    # ======================================
    # RANKING DA RODADA
    # ======================================

    ranking = gerar_ranking(sala)

    socketio.emit(
        "rodada_terminou",
        {
            "rodada":
                sala["rodada"],

            "jogadores":
                estado_jogadores(sala),

            "ranking":
                ranking,

            "tempo":
                sala["tempo_rodada"],

            "max_jogadores":
                sala["max_jogadores"]
        },
        to=codigo
    )

    atualizar_lobby(codigo)

    # ======================================
    # ÚLTIMA RODADA
    # ======================================

    if sala["rodada"] >= sala["total_rodadas"]:

        socketio.start_background_task(
            finalizar_depois,
            codigo
        )

        return

    # ======================================
    # MODO SOLO
    # ======================================

    if sala["modo"] == "solo":

        sala["rodada"] += 1

        iniciar_rodada(codigo)

        return

    # ======================================
    # MULTIPLAYER
    # ======================================

    if sala["intervalo_habilitado"]:

        # Intervalo de 2 minutos
        iniciar_intervalo(codigo)

    else:

        # Sem intervalo
        sala["rodada"] += 1

        iniciar_rodada(codigo)


# ==========================================
# INICIAR INTERVALO
# ==========================================

def iniciar_intervalo(codigo):

    if codigo not in salas:
        return

    sala = salas[codigo]

    if not sala["jogo_iniciado"]:
        return

    # ======================================
    # SE INTERVALO ESTIVER DESATIVADO
    # ======================================

    if not sala["intervalo_habilitado"]:

        sala["rodada"] += 1

        iniciar_rodada(codigo)

        return

    # ======================================
    # ÚLTIMA RODADA
    # ======================================

    if sala["rodada"] >= sala["total_rodadas"]:

        finalizar_jogo(codigo)

        return

    # ======================================
    # INICIAR INTERVALO
    # ======================================

    sala["em_intervalo"] = True

    sala["fim_intervalo"] = (
        time.time()
        + INTERVALO_RODADAS
    )

    sala["encerrando_rodada"] = False

    socketio.emit(
        "intervalo_iniciado",
        {
            "rodada":
                sala["rodada"],

            "proxima_rodada":
                sala["rodada"] + 1,

            "tempo":
                INTERVALO_RODADAS,

            "fim":
                sala["fim_intervalo"]
        },
        to=codigo
    )

    atualizar_lobby(codigo)


# ==========================================
# INICIAR PRÓXIMA RODADA
# ==========================================

def iniciar_proxima_rodada(codigo):

    if codigo not in salas:
        return

    sala = salas[codigo]

    if not sala["jogo_iniciado"]:
        return

    if not sala["em_intervalo"]:
        return

    sala["em_intervalo"] = False

    sala["fim_intervalo"] = None

    sala["rodada"] += 1

    iniciar_rodada(codigo)


# ==========================================
# PULAR INTERVALO
# ==========================================

@socketio.on("pular_intervalo")
def pular_intervalo():

    codigo, nome, sala = jogador_atual()

    if not sala:

        emit(
            "erro_socket",
            {
                "mensagem":
                    "conecte-se à sala primeiro"
            }
        )

        return

    if sala["modo"] == "solo":
        return

    if nome != sala["host"]:

        emit(
            "erro_socket",
            {
                "mensagem":
                    "somente o host pode pular o intervalo"
            }
        )

        return

    if not sala["jogo_iniciado"]:
        return

    if not sala["em_intervalo"]:
        return

    iniciar_proxima_rodada(codigo)


# ==========================================
# FINALIZAR DEPOIS
# ==========================================

def finalizar_depois(codigo):

    socketio.sleep(2)

    finalizar_jogo(codigo)


# ==========================================
# FINALIZAR JOGO
# ==========================================

def finalizar_jogo(codigo):

    if codigo not in salas:
        return

    sala = salas[codigo]

    # Guardamos a rodada antes de finalizar
    rodada_final = sala["rodada"]

    sala["jogo_iniciado"] = False

    sala["fim_rodada"] = None

    sala["fim_intervalo"] = None

    sala["letra"] = None

    sala["timer_ativo"] = False

    sala["encerrando_rodada"] = False

    sala["em_intervalo"] = False

    # ======================================
    # RANKING
    # ======================================

    ranking = gerar_ranking(sala)

    vencedor = (
        ranking[0]["nome"]
        if ranking
        else None
    )

    socketio.emit(
        "jogo_terminou",
        {
            "vencedor":
                vencedor,

            "ranking":
                ranking,

            "jogadores":
                estado_jogadores(sala),

            "total_rodadas":
                sala["total_rodadas"],

            "rodada":
                rodada_final
        },
        to=codigo
    )

    atualizar_lobby(codigo)


# ==========================================
# ENVIAR CARRO
# ==========================================

@socketio.on("enviar_carro")
def enviar_carro(data):

    codigo, nome, sala = jogador_atual()

    if not sala:

        emit(
            "resposta_carro",
            {
                "sucesso":
                    False,

                "mensagem":
                    "conexão perdida"
            }
        )

        return

    carro = str(
        data.get(
            "carro",
            ""
        )
    ).strip()

    if not carro:
        return

    if not sala["jogo_iniciado"]:

        emit(
            "resposta_carro",
            {
                "sucesso":
                    False,

                "mensagem":
                    "a partida ainda não começou"
            }
        )

        return

    # ======================================
    # NÃO PODE RESPONDER DURANTE INTERVALO
    # ======================================

    if sala["em_intervalo"]:

        emit(
            "resposta_carro",
            {
                "sucesso":
                    False,

                "mensagem":
                    "aguarde a próxima rodada!"
            }
        )

        return

    if sala["vidas"].get(
        nome,
        0
    ) <= 0:

        emit(
            "resposta_carro",
            {
                "sucesso":
                    False,

                "mensagem":
                    "você foi eliminado!",

                "vidas":
                    0,

                "nome":
                    nome
            }
        )

        return

    if nome in sala["responderam"]:

        emit(
            "resposta_carro",
            {
                "sucesso":
                    False,

                "mensagem":
                    "você já respondeu nesta rodada! ✓",

                "vidas":
                    sala["vidas"][nome],

                "nome":
                    nome
            }
        )

        return

    if (
        not sala["fim_rodada"]
        or time.time() >= sala["fim_rodada"]
    ):

        return

    n = normalizar_carro(carro)

    # ======================================
    # ERRO
    # ======================================

    def erro(mensagem):

        sala["vidas"][nome] -= 1

        if sala["vidas"][nome] < 0:
            sala["vidas"][nome] = 0

        emit(
            "resposta_carro",
            {
                "sucesso":
                    False,

                "mensagem":
                    mensagem,

                "vidas":
                    sala["vidas"][nome],

                "nome":
                    nome
            }
        )

        atualizar_lobby(codigo)

    # ======================================
    # CARRO REPETIDO
    # ======================================

    if n in sala["carros_usados"]:

        erro(
            "esse carro já foi usado! -1 vida"
        )

        return

    # ======================================
    # CARRO INEXISTENTE
    # ======================================

    if n not in carros_normalizados:

        erro(
            "esse modelo não está na coleção! -1 vida"
        )

        return

    # ======================================
    # LETRA ERRADA
    # ======================================

    letra_normalizada = normalizar_carro(
        sala["letra"]
    )

    if not n.startswith(
        letra_normalizada
    ):

        erro(
            f"esse carro não começa com "
            f"{sala['letra']}! -1 vida"
        )

        return

    # ======================================
    # CARRO ACEITO
    # ======================================

    sala["carros_usados"].append(n)

    sala["responderam"].add(nome)

    # ======================================
    # PONTOS
    # ======================================

    sala["pontos"][nome] += 1

    sala["respostas_validas"][nome] += 1

    socketio.emit(
        "carro_aceito",
        {
            "nome":
                nome,

            "carro":
                carro,

            "vidas":
                sala["vidas"][nome],

            "pontos":
                sala["pontos"][nome]
        },
        to=codigo
    )

    atualizar_lobby(codigo)

    # ======================================
    # TODOS RESPONDERAM
    # ======================================

    if todos_responderam(codigo):

        terminar_rodada(
            codigo,
            por_tempo=False
        )


# ==========================================
# CHAT
# ==========================================

@socketio.on("mensagem_chat")
def mensagem_chat(data):

    codigo, nome, sala = jogador_atual()

    if not sala:

        emit(
            "chat_bloqueado",
            {
                "mensagem":
                    "conexão perdida"
            }
        )

        return

    # ======================================
    # SOLO NÃO POSSUI CHAT
    # ======================================

    if sala["modo"] == "solo":

        emit(
            "chat_bloqueado",
            {
                "mensagem":
                    "o chat não está disponível no modo solo"
            }
        )

        return

    # ======================================
    # CHAT BLOQUEADO DURANTE A RODADA
    # ======================================

    if sala["jogo_iniciado"] and not sala["em_intervalo"]:

        emit(
            "chat_bloqueado",
            {
                "mensagem":
                    "o chat fica liberado somente durante o intervalo"
            }
        )

        return

    mensagem = str(
        data.get(
            "mensagem",
            ""
        )
    ).strip()

    if not mensagem:
        return

    # ======================================
    # CHAT LIBERADO
    # ======================================

    socketio.emit(
        "mensagem_chat",
        {
            "nome":
                nome,

            "mensagem":
                mensagem
        },
        to=codigo
    )


# ==========================================
# EXPULSAR JOGADOR
# ==========================================

@socketio.on("expulsar_jogador")
def expulsar_jogador(data):

    codigo, nome, sala = jogador_atual()

    if not sala:
        emit(
            "erro_socket",
            {
                "mensagem":
                    "conecte-se à sala primeiro"
            }
        )
        return

    # ======================================
    # SOMENTE O HOST PODE EXPULSAR
    # ======================================

    if nome != sala["host"]:
        emit(
            "erro_socket",
            {
                "mensagem":
                    "somente o host pode expulsar jogadores"
            }
        )
        return

    # ======================================
    # SÓ PODE EXPULSAR NO LOBBY
    # ======================================

    if sala["jogo_iniciado"]:
        emit(
            "erro_socket",
            {
                "mensagem":
                    "não é possível expulsar jogadores durante a partida"
            }
        )
        return

    jogador_expulso = str(
        data.get(
            "nome",
            ""
        )
    ).strip()

    # ======================================
    # VALIDAÇÕES
    # ======================================

    if not jogador_expulso:
        return

    if jogador_expulso == nome:
        emit(
            "erro_socket",
            {
                "mensagem":
                    "você não pode expulsar a si mesmo"
            }
        )
        return

    if jogador_expulso not in sala["jogadores"]:
        emit(
            "erro_socket",
            {
                "mensagem":
                    "jogador não encontrado na sala"
            }
        )
        return

    # ======================================
    # DESCOBRIR SID DO JOGADOR
    # ======================================

    sid_expulso = None

    for sid, conexao in list(conexoes.items()):
        if (
            conexao["codigo"] == codigo
            and conexao["nome"] == jogador_expulso
        ):
            sid_expulso = sid
            break

    # ======================================
    # REMOVER DO ESTADO DA SALA
    # ======================================

    sala["jogadores"].remove(jogador_expulso)

    sala["vidas"].pop(
        jogador_expulso,
        None
    )

    sala["pontos"].pop(
        jogador_expulso,
        None
    )

    sala["respostas_validas"].pop(
        jogador_expulso,
        None
    )

    sala["responderam"].discard(
        jogador_expulso
    )

    # ======================================
    # AVISAR TODOS OS JOGADORES
    # ======================================

    socketio.emit(
        "jogador_expulso",
        {
            "nome": jogador_expulso
        },
        to=codigo
    )

    # ======================================
    # AVISAR O EXPULSO
    # ======================================

    if sid_expulso:

        socketio.emit(
            "voce_foi_expulso",
            {
                "mensagem":
                    "você foi expulso da sala pelo host."
            },
            to=sid_expulso
        )

        # Remove a conexão
        conexoes.pop(
            sid_expulso,
            None
        )

        # Desconecta o socket
        try:
            disconnect(
                sid_expulso
            )
        except Exception:
            pass

    # ======================================
    # ATUALIZAR LOBBY
    # ======================================

    atualizar_lobby(codigo)

# ==========================================
# DISCONNECT
# ==========================================

@socketio.on("disconnect")
def desconectado():

    conexao = conexoes.pop(
        request.sid,
        None
    )

    if conexao:

        atualizar_lobby(
            conexao["codigo"]
        )


# ==========================================
# SERVIDOR
# ==========================================

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=False
    )