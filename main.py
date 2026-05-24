import discord
from discord.ext import commands
import json
import qrcode
import os

CONFIG_FILE = "config.json"
PRODUTOS_FILE = "produtos.json"

ROXO = 0x6D1CFF
VERDE = 0x00FF88
VERMELHO = 0xFF3B3B


def carregar_json(arquivo):
    with open(arquivo, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_json(arquivo, dados):
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)


config = carregar_json(CONFIG_FILE)
produtos = carregar_json(PRODUTOS_FILE)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def salvar_produtos():
    salvar_json(PRODUTOS_FILE, produtos)


def is_staff_membro(membro):
    cargo = membro.guild.get_role(config["cargo_staff_id"])
    return cargo in membro.roles


def gerar_qr(texto, nome):
    os.makedirs("pagamentos", exist_ok=True)
    caminho = f"pagamentos/{nome}.png"
    qr = qrcode.make(texto)
    qr.save(caminho)
    return caminho


@bot.event
async def on_ready():
    print(f"Bot online como {bot.user}")


class ComprarView(discord.ui.View):
    def __init__(self, produto_id):
        super().__init__(timeout=None)
        self.produto_id = produto_id

    @discord.ui.button(label="Comprar", style=discord.ButtonStyle.green)
    async def comprar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.produto_id not in produtos:
            await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
            return

        produto = produtos[self.produto_id]

        if produto["estoque"] <= 0:
            await interaction.response.send_message("❌ Produto sem estoque.", ephemeral=True)
            return

        categoria = interaction.guild.get_channel(config["categoria_carrinhos_id"])

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }

        cargo_staff = interaction.guild.get_role(config["cargo_staff_id"])
        if cargo_staff:
            overwrites[cargo_staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        canal = await interaction.guild.create_text_channel(
            name=f"🛒-{interaction.user.name}",
            category=categoria,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title=f"{interaction.user.name} | Carrinho",
            description=(
                f"🛒 **Produto:** {produto['nome']}\n"
                f"💸 **Valor:** R$ {produto['preco']:.2f}\n"
                f"📦 **Estoque:** {produto['estoque']}"
            ),
            color=ROXO
        )

        if produto.get("imagem"):
            embed.set_thumbnail(url=produto["imagem"])

        await canal.send(
            content=interaction.user.mention,
            embed=embed,
            view=PagamentoView(self.produto_id, interaction.user.id)
        )

        await interaction.response.send_message(f"✅ Carrinho criado: {canal.mention}", ephemeral=True)


class PagamentoView(discord.ui.View):
    def __init__(self, produto_id, comprador_id):
        super().__init__(timeout=None)
        self.produto_id = produto_id
        self.comprador_id = comprador_id

    async def verificar(self, interaction):
        if interaction.user.id != self.comprador_id:
            await interaction.response.send_message("❌ Este carrinho não é seu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pix", emoji="💠", style=discord.ButtonStyle.blurple)
    async def pix(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.verificar(interaction):
            return

        produto = produtos[self.produto_id]
        codigo_pix = config["pix_chave"]
        qr_path = gerar_qr(codigo_pix, f"pix_{interaction.channel.id}")

        embed = discord.Embed(
            title="🟢 Aguardando pagamento...",
            description=(
                f"📦 **Produto:** {produto['nome']}\n"
                f"💸 **Valor:** R$ {produto['preco']:.2f}\n\n"
                f"📋 **Pix copia e cola:**\n```{codigo_pix}```"
            ),
            color=VERDE
        )

        file = discord.File(qr_path, filename="qrcode.png")
        embed.set_image(url="attachment://qrcode.png")

        await interaction.response.send_message(
            embed=embed,
            file=file,
            view=ConfirmarView(self.produto_id, self.comprador_id)
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.red)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.verificar(interaction):
            return

        await interaction.response.send_message("🗑️ Carrinho cancelado.")
        await interaction.channel.delete()


class ConfirmarView(discord.ui.View):
    def __init__(self, produto_id, comprador_id):
        super().__init__(timeout=None)
        self.produto_id = produto_id
        self.comprador_id = comprador_id

    @discord.ui.button(label="Confirmar Pagamento", emoji="✅", style=discord.ButtonStyle.green)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.comprador_id:
            await interaction.response.send_message("❌ Este carrinho não é seu.", ephemeral=True)
            return

        cargo = interaction.guild.get_role(config["cargo_staff_id"])

        embed = discord.Embed(
            title="💰 Pagamento enviado",
            description=f"{interaction.user.mention} informou que realizou o pagamento.\n\n📦 Produto: `{self.produto_id}`",
            color=ROXO
        )

        await interaction.response.send_message(
            content=cargo.mention if cargo else None,
            embed=embed,
            view=StaffView(self.produto_id, self.comprador_id)
        )


class StaffView(discord.ui.View):
    def __init__(self, produto_id, comprador_id):
        super().__init__(timeout=None)
        self.produto_id = produto_id
        self.comprador_id = comprador_id

    @discord.ui.button(label="Aprovar", emoji="✅", style=discord.ButtonStyle.green)
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff_membro(interaction.user):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return

        produto = produtos[self.produto_id]

        if produto["estoque"] <= 0:
            await interaction.response.send_message("❌ Produto sem estoque.", ephemeral=True)
            return

        produto["estoque"] -= 1
        salvar_produtos()

        usuario = interaction.guild.get_member(self.comprador_id)
        cargo_cliente = interaction.guild.get_role(config["cargo_cliente_id"])

        if usuario and cargo_cliente:
            await usuario.add_roles(cargo_cliente)

        entrega = produto.get("entrega", "Nenhuma entrega configurada.")

        if usuario:
            try:
                await usuario.send(
                    f"✅ **Compra aprovada!**\n\n"
                    f"📦 Produto: **{produto['nome']}**\n\n"
                    f"🎁 **Entrega:**\n```{entrega}```"
                )
            except:
                await interaction.channel.send("⚠️ Não consegui enviar DM para o cliente.")

        embed = discord.Embed(
            title="✅ Compra aprovada",
            description=(
                f"📦 Produto: {produto['nome']}\n"
                f"💸 Valor: R$ {produto['preco']:.2f}\n"
                f"📦 Estoque restante: {produto['estoque']}"
            ),
            color=VERDE
        )

        await interaction.response.send_message(content=usuario.mention if usuario else None, embed=embed)


class CriarProdutoModal(discord.ui.Modal, title="Criar Produto"):
    produto_id = discord.ui.TextInput(label="ID do produto", placeholder="produto1")
    nome = discord.ui.TextInput(label="Nome do produto")
    preco = discord.ui.TextInput(label="Preço", placeholder="13.50")
    estoque = discord.ui.TextInput(label="Estoque", placeholder="10")
    descricao = discord.ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        if not is_staff_membro(interaction.user):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return

        produtos[str(self.produto_id)] = {
            "nome": str(self.nome),
            "preco": float(str(self.preco).replace(",", ".")),
            "estoque": int(str(self.estoque)),
            "descricao": str(self.descricao),
            "imagem": "",
            "entrega": "Nenhuma entrega configurada."
        }

        salvar_produtos()
        await interaction.response.send_message(f"✅ Produto `{self.produto_id}` criado.", ephemeral=True)


class EditarNomeModal(discord.ui.Modal, title="Editar Nome"):
    produto_id = discord.ui.TextInput(label="ID do produto")
    nome = discord.ui.TextInput(label="Novo nome")

    async def on_submit(self, interaction):
        pid = str(self.produto_id)

        if pid not in produtos:
            await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
            return

        produtos[pid]["nome"] = str(self.nome)
        salvar_produtos()
        await interaction.response.send_message("✅ Nome alterado.", ephemeral=True)


class EditarPrecoModal(discord.ui.Modal, title="Editar Preço"):
    produto_id = discord.ui.TextInput(label="ID do produto")
    preco = discord.ui.TextInput(label="Novo preço")

    async def on_submit(self, interaction):
        pid = str(self.produto_id)

        if pid not in produtos:
            await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
            return

        produtos[pid]["preco"] = float(str(self.preco).replace(",", "."))
        salvar_produtos()
        await interaction.response.send_message("✅ Preço alterado.", ephemeral=True)


class EditarEstoqueModal(discord.ui.Modal, title="Editar Estoque"):
    produto_id = discord.ui.TextInput(label="ID do produto")
    estoque = discord.ui.TextInput(label="Novo estoque")

    async def on_submit(self, interaction):
        pid = str(self.produto_id)

        if pid not in produtos:
            await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
            return

        produtos[pid]["estoque"] = int(str(self.estoque))
        salvar_produtos()
        await interaction.response.send_message("✅ Estoque alterado.", ephemeral=True)


class EditarDescricaoModal(discord.ui.Modal, title="Editar Descrição"):
    produto_id = discord.ui.TextInput(label="ID do produto")
    descricao = discord.ui.TextInput(label="Nova descrição", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        pid = str(self.produto_id)

        if pid not in produtos:
            await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
            return

        produtos[pid]["descricao"] = str(self.descricao)
        salvar_produtos()
        await interaction.response.send_message("✅ Descrição alterada.", ephemeral=True)


class EditarImagemModal(discord.ui.Modal, title="Editar Imagem"):
    produto_id = discord.ui.TextInput(label="ID do produto")
    imagem = discord.ui.TextInput(label="Link da imagem")

    async def on_submit(self, interaction):
        pid = str(self.produto_id)

        if pid not in produtos:
            await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
            return

        produtos[pid]["imagem"] = str(self.imagem)
        salvar_produtos()
        await interaction.response.send_message("✅ Imagem alterada.", ephemeral=True)


class EditarEntregaModal(discord.ui.Modal, title="Editar Entrega"):
    produto_id = discord.ui.TextInput(label="ID do produto")
    entrega = discord.ui.TextInput(label="Entrega enviada na DM", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        pid = str(self.produto_id)

        if pid not in produtos:
            await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
            return

        produtos[pid]["entrega"] = str(self.entrega)
        salvar_produtos()
        await interaction.response.send_message("✅ Entrega alterada.", ephemeral=True)


class PainelAdmin(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check(self, interaction):
        if not is_staff_membro(interaction.user):
            await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Criar Produto", emoji="➕", style=discord.ButtonStyle.green)
    async def criar(self, interaction, button):
        if await self.check(interaction):
            await interaction.response.send_modal(CriarProdutoModal())

    @discord.ui.button(label="Editar Nome", emoji="✏️", style=discord.ButtonStyle.blurple)
    async def nome(self, interaction, button):
        if await self.check(interaction):
            await interaction.response.send_modal(EditarNomeModal())

    @discord.ui.button(label="Editar Preço", emoji="💸", style=discord.ButtonStyle.blurple)
    async def preco(self, interaction, button):
        if await self.check(interaction):
            await interaction.response.send_modal(EditarPrecoModal())

    @discord.ui.button(label="Editar Estoque", emoji="📦", style=discord.ButtonStyle.blurple)
    async def estoque(self, interaction, button):
        if await self.check(interaction):
            await interaction.response.send_modal(EditarEstoqueModal())

    @discord.ui.button(label="Editar Descrição", emoji="📝", style=discord.ButtonStyle.gray)
    async def descricao(self, interaction, button):
        if await self.check(interaction):
            await interaction.response.send_modal(EditarDescricaoModal())

    @discord.ui.button(label="Editar Imagem", emoji="🖼️", style=discord.ButtonStyle.gray)
    async def imagem(self, interaction, button):
        if await self.check(interaction):
            await interaction.response.send_modal(EditarImagemModal())

    @discord.ui.button(label="Editar Entrega", emoji="🎁", style=discord.ButtonStyle.gray)
    async def entrega(self, interaction, button):
        if await self.check(interaction):
            await interaction.response.send_modal(EditarEntregaModal())

    @discord.ui.button(label="Listar Produtos", emoji="📋", style=discord.ButtonStyle.red)
    async def listar(self, interaction, button):
        if not await self.check(interaction):
            return

        texto = "📦 **Produtos cadastrados:**\n\n"

        for pid, produto in produtos.items():
            texto += f"`{pid}` | {produto['nome']} | R$ {produto['preco']:.2f} | Estoque: {produto['estoque']}\n"

        await interaction.response.send_message(texto, ephemeral=True)


@bot.command()
async def painelrejeitados(ctx):
    if not is_staff_membro(ctx.author):
        await ctx.send("❌ Sem permissão.")
        return

    embed = discord.Embed(
        title="🛠️ Sistema Rejeitados",
        description=(
            "📦 **GERENCIAMENTO DE PRODUTOS**\n\n"
            "➕ Criar Produto\n"
            "✏️ Editar Nome\n"
            "💸 Editar Preço\n"
            "📦 Editar Estoque\n"
            "📝 Editar Descrição\n"
            "🖼️ Editar Imagem\n"
            "🎁 Editar Entrega\n"
            "📋 Listar Produtos"
        ),
        color=ROXO
    )

    await ctx.send(embed=embed, view=PainelAdmin())


@bot.command()
async def painel(ctx, produto_id):
    if produto_id not in produtos:
        await ctx.send("❌ Produto não encontrado.")
        return

    produto = produtos[produto_id]

    embed = discord.Embed(
        description=(
            f"{produto['descricao']}\n\n"
            f"🍔 | **Nome:** {produto['nome']}\n"
            f"💸 | **Preço:** R$ {produto['preco']:.2f}\n"
            f"📦 | **Estoque:** {produto['estoque']}"
        ),
        color=ROXO
    )

    if produto.get("imagem"):
        embed.set_image(url=produto["imagem"])

    await ctx.send(embed=embed, view=ComprarView(produto_id))


@bot.command()
async def ajuda(ctx):
    await ctx.send("`!painelrejeitados`\n`!painel produto1`")


bot.run(config["token"])