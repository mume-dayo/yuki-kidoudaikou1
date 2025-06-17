import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
import datetime
from typing import Optional
import openai
import deepl

# 設定ファイルの読み込み
def load_config():
    if not os.path.exists("config.json"):
        return {"allowed_user_ids": []}
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
allowed_user_ids = config.get("allowed_user_ids", [])

# OpenAI と DeepL の初期化
openai_client = None
deepl_translator = None

try:
    openai_api_key = os.getenv('OPENAI_API_KEY')
    if openai_api_key:
        openai_client = openai.OpenAI(api_key=openai_api_key)
        print("OpenAI API 初期化成功")
    else:
        print("OpenAI API キーが設定されていません")
except Exception as e:
    print(f"OpenAI API 初期化エラー: {e}")

try:
    deepl_api_key = os.getenv('DEEPL_API_KEY')
    if deepl_api_key:
        deepl_translator = deepl.Translator(deepl_api_key)
        print("DeepL API 初期化成功")
    else:
        print("DeepL API キーが設定されていません")
except Exception as e:
    print(f"DeepL API 初期化エラー: {e}")

LEVEL_DATA_FILE = "level_data.json"  # レベルデータを保存するファイル

def load_level_data():
    if not os.path.exists(LEVEL_DATA_FILE):
        return {}
    try:
        with open(LEVEL_DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # ファイルが破損している場合は空のデータで初期化
        return {}

def save_level_data(data):
    with open(LEVEL_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# XPを加算し、レベルアップ判定を行う関数
def add_xp(user_id, xp):
    level_data = load_level_data()
    user_id = str(user_id)  # user_idを文字列に変換
    if user_id not in level_data:
        level_data[user_id] = {"level": 1, "xp": 0}

    level_data[user_id]["xp"] += xp
    current_level = level_data[user_id]["level"]
    current_xp = level_data[user_id]["xp"]
    xp_needed_for_next_level = calculate_xp_needed(current_level)

    leveled_up = False
    new_level = current_level

    while current_xp >= xp_needed_for_next_level:
        current_xp -= xp_needed_for_next_level
        new_level += 1
        xp_needed_for_next_level = calculate_xp_needed(new_level)
        leveled_up = True

    level_data[user_id]["level"] = new_level
    level_data[user_id]["xp"] = current_xp
    save_level_data(level_data)

    return leveled_up, new_level

# レベルアップに必要なXPを計算する関数
def calculate_xp_needed(level):
    return 100 * level ** 2  # 例：レベルが上がるごとに必要なXPが増加

# 新しいチケットシステム
class TicketView(discord.ui.View):
    def __init__(self, staff_role: discord.Role, category: discord.CategoryChannel):
        super().__init__(timeout=None)
        self.staff_role = staff_role
        self.category = category

    @discord.ui.button(label="🎫 チケット作成", style=discord.ButtonStyle.primary, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # パラメータが設定されていない場合（ボット再起動時など）
        if not self.staff_role or not self.category:
            await interaction.response.send_message("❌ チケット設定にエラーがあります。管理者にお問い合わせください。", ephemeral=True)
            return
        # 既存のチケットがあるかチェック
        existing_ticket = discord.utils.get(interaction.guild.channels, name=f"ticket-{interaction.user.name.lower()}")
        if existing_ticket:
            await interaction.response.send_message(f"既にチケット {existing_ticket.mention} が存在します。", ephemeral=True)
            return

        # チケットチャンネル作成
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            self.staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }

        ticket_channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name.lower()}",
            category=self.category,
            overwrites=overwrites
        )

        # チケット開始メッセージ
        embed = discord.Embed(
            title="🎫 チケット作成完了",
            description=f"{interaction.user.mention} のチケットが作成されました。\n\nスタッフが対応するまでお待ちください。",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 作成者", value=interaction.user.display_name, inline=True)
        embed.add_field(name="📅 作成日時", value=discord.utils.utcnow().strftime("%Y/%m/%d %H:%M:%S"), inline=True)
        embed.set_footer(text="下のボタンでチケットを削除できます")

        close_view = CloseTicketView()
        await ticket_channel.send(f"{interaction.user.mention} {self.staff_role.mention}", embed=embed, view=close_view)

        await interaction.response.send_message(f"チケット {ticket_channel.mention} を作成しました！", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🗑️ チケット削除", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 確認メッセージ
        embed = discord.Embed(
            title="⚠️ チケット削除の確認",
            description="本当にこのチケットを削除しますか？\nこの操作は取り消せません。",
            color=discord.Color.orange()
        )

        confirm_view = ConfirmCloseView()
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)

class ConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ 削除する", style=discord.ButtonStyle.danger, custom_id="confirm_close_btn")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("チケットを削除しています...", ephemeral=True)
        await interaction.channel.delete()

    @discord.ui.button(label="❌ キャンセル", style=discord.ButtonStyle.secondary, custom_id="cancel_close_btn")
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("削除をキャンセルしました。", ephemeral=True)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# メンション回数を追跡する辞書
mention_count = {}

# 荒らし対策用の変数
user_message_timestamps = {}  # ユーザーの最後のメッセージ時間を追跡
spam_warnings = {}  # スパム警告回数を追跡

# 不適切な単語リスト（設定可能）
def get_bad_words():
    return config.get("bad_words", ["spam", "アホ", "バカ", "死ね", "殺す"])

# 短時間での連続投稿をチェック
def is_spam_message(user_id, current_time):
    if user_id not in user_message_timestamps:
        user_message_timestamps[user_id] = []

    # 過去10秒以内のメッセージを取得
    recent_messages = [t for t in user_message_timestamps[user_id] if current_time - t < 10]
    user_message_timestamps[user_id] = recent_messages + [current_time]

    # 10秒以内に5回以上メッセージを送信した場合はスパム
    return len(recent_messages) >= 4

# 不適切な単語をチェック
def contains_bad_words(message_content):
    bad_words = get_bad_words()
    message_lower = message_content.lower()
    for word in bad_words:
        if word.lower() in message_lower:
            return True, word
    return False, None

@bot.event
async def on_ready(): 
    print(f"{bot.user}ログイン成功 (ID: {bot.user.id})")
    print("------")

    # 永続ビューを追加（ボット再起動時のインタラクション失敗を防ぐ）
    bot.add_view(CloseTicketView())
    bot.add_view(ConfirmCloseView())

    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.event
async def on_member_join(member):
    # ログチャンネルへの入室ログ送信
    log_channel_id = config.get("log_channel_id")
    if log_channel_id:
        log_channel = bot.get_channel(log_channel_id)
        if log_channel:
            embed = discord.Embed(
                title="🟢 メンバー参加",
                description=f"{member.mention} がサーバーに参加しました",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="ユーザー名", value=member.name, inline=True)
            embed.add_field(name="ユーザーID", value=member.id, inline=True)
            embed.add_field(name="アカウント作成日", value=member.created_at.strftime("%Y/%m/%d %H:%M:%S"), inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"総メンバー数: {member.guild.member_count}")

            await log_channel.send(embed=embed)

    # DMでウェルカムメッセージを送信（設定で有効になっている場合のみ）
    welcome_dm_enabled = config.get("welcome_dm_enabled", True)  # デフォルトで有効
    if welcome_dm_enabled:
        try:
            welcome_embed = discord.Embed(
                title="🎉 ようこそ！",
                description=f"**{member.guild.name}** へようこそ、{member.name}さん！",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            welcome_embed.add_field(
                name="サーバー情報",
                value=f"サーバー名: {member.guild.name}\n"
                      f"総メンバー数: {member.guild.member_count}人",
                inline=False
            )
            welcome_embed.add_field(
                name="お願い",
                value="・サーバールールをお読みください\n"
                      "・認証が必要な場合は認証チャンネルで認証してください\n"
                      "・何かご不明な点がございましたらスタッフまでお声がけください",
                inline=False
            )
            welcome_embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
            welcome_embed.set_footer(text=f"参加日時: {discord.utils.utcnow().strftime('%Y年%m月%d日 %H:%M:%S')}")

            await member.send(embed=welcome_embed)
            print(f"ウェルカムメッセージを {member.name} に送信しました")

        except discord.Forbidden:
            print(f"ウェルカムメッセージの送信に失敗しました: {member.name} のDMが無効です")
        except Exception as e:
            print(f"ウェルカムメッセージ送信エラー: {e}")

@bot.event
async def on_member_remove(member):
    log_channel_id = config.get("log_channel_id")
    if not log_channel_id:
        return

    log_channel = bot.get_channel(log_channel_id)
    if not log_channel:
        return

    embed = discord.Embed(
        title="🔴 メンバー退出",
        description=f"{member.name} がサーバーから退出しました",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="ユーザー名", value=member.name, inline=True)
    embed.add_field(name="ユーザーID", value=member.id, inline=True)
    if member.joined_at:
        embed.add_field(name="参加日", value=member.joined_at.strftime("%Y/%m/%d %H:%M:%S"), inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"総メンバー数: {member.guild.member_count}")

    await log_channel.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    current_time = datetime.datetime.now().timestamp()
    user_id = message.author.id

    # 荒らし対策機能が有効かチェック
    anti_spam_enabled = config.get("anti_spam_enabled", True)
    if not anti_spam_enabled:
        # レベルシステムが有効かチェック
        level_system_enabled = config.get("level_system_enabled", True)
        if level_system_enabled and not message.author.bot:
            # メッセージ送信でXPを獲得（ランダムで15-25XP）
            xp_gain = random.randint(15, 25)
            leveled_up, new_level = add_xp(message.author.id, xp_gain)

            if leveled_up:
                # レベルアップ通知が有効な場合のみ送信
                levelup_notifications = config.get("levelup_notifications", True)
                if levelup_notifications:
                    embed = discord.Embed(
                        title="🎉 レベルアップ！",
                        description=f"{message.author.mention} がレベル **{new_level}** に到達しました！",
                        color=discord.Color.gold()
                    )
                    embed.set_thumbnail(url=message.author.display_avatar.url)
                    await message.channel.send(embed=embed)

        await bot.process_commands(message)
        return

    # 新規アカウント制限チェック
    account_age_days = (datetime.datetime.now() - message.author.created_at.replace(tzinfo=None)).days
    min_account_age = config.get("min_account_age_days", 7)
    if account_age_days < min_account_age:
        try:
            await message.delete()
            embed = discord.Embed(
                title="🚫 新規アカウント制限",
                description=f"{message.author.mention} アカウント作成から{min_account_age}日経過していないため、メッセージが削除されました。",
                color=discord.Color.red()
            )
            warning_msg = await message.channel.send(embed=embed)
            await warning_msg.delete(delay=10)
            return
        except discord.Forbidden:
            pass

    # 不適切な単語チェック
    contains_bad, bad_word = contains_bad_words(message.content)
    if contains_bad:
        try:
            await message.delete()

            # 警告回数を増やす
            if user_id not in spam_warnings:
                spam_warnings[user_id] = 0
            spam_warnings[user_id] += 1

            embed = discord.Embed(
                title="🚫 不適切な単語検出",
                description=f"{message.author.mention} 不適切な単語「{bad_word}」が検出されたため、メッセージを削除しました。\n警告回数: {spam_warnings[user_id]}/3",
                color=discord.Color.red()
            )
            warning_msg = await message.channel.send(embed=embed)
            await warning_msg.delete(delay=10)

            # 3回警告でタイムアウト
            if spam_warnings[user_id] >= 3:
                timeout_duration = datetime.timedelta(minutes=30)
                await message.author.timeout(timeout_duration, reason="不適切な単語の使用（3回警告）")
                spam_warnings[user_id] = 0  # リセット

            return
        except discord.Forbidden:
            pass

    # スパムメッセージチェック
    if is_spam_message(user_id, current_time):
        try:
            await message.delete()

            # 警告回数を増やす
            if user_id not in spam_warnings:
                spam_warnings[user_id] = 0
            spam_warnings[user_id] += 1

            timeout_duration = datetime.timedelta(minutes=5 * spam_warnings[user_id])  # 警告回数に応じて時間延長
            await message.author.timeout(timeout_duration, reason="スパム行為による自動タイムアウト")

            embed = discord.Embed(
                title="🚫 スパム検出",
                description=f"{message.author.mention} が短時間で大量のメッセージを送信したため、{timeout_duration.total_seconds()//60}分間タイムアウトされました。",
                color=discord.Color.red()
            )
            warning_msg = await message.channel.send(embed=embed)
            await warning_msg.delete(delay=15)

            return
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ エラー",
                description="ボットにタイムアウト権限がありません。",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)

    # メンションの数をカウント
    mention_count_in_message = len(message.mentions)

    if mention_count_in_message >= 2:
        # 2回以上メンションしている場合、即座にタイムアウト
        try:
            # 設定されたタイムアウト時間を使用（デフォルト10分）
            timeout_minutes = config.get("timeout_minutes", 10)
            timeout_duration = datetime.timedelta(minutes=timeout_minutes)
            await message.author.timeout(timeout_duration, reason="2回以上のメンションによる自動タイムアウト")

            embed = discord.Embed(
                title="⚠️ 自動タイムアウト",
                description=f"{message.author.mention} が1つのメッセージで2回以上メンションしたため、{timeout_minutes}分間タイムアウトされました。",
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed)

            # メッセージを削除
            await message.delete()

        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ エラー",
                description="ボットにタイムアウト権限がありません。",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)
        except Exception as e:
            print(f"タイムアウトエラー: {e}")

    # 「ゆき」「yuki」「雪」への自動反応
    message_lower = message.content.lower()
    if any(keyword in message_lower for keyword in ["ゆき", "yuki", "雪"]):
        embed = discord.Embed(
            title="❄️ 雪について",
            description="雪（ゆき/yuki）は、このbotの作成者であり、とても可愛い女の子です！💕",
            color=discord.Color.from_rgb(173, 216, 230)  # 薄い青色（雪をイメージ）
        )
        embed.add_field(name="特徴", value="・botの開発者\n・可愛い女の子\n・プログラミングが得意", inline=False)
        embed.set_footer(text="雪ちゃんに感謝！ ❄️")
        await message.channel.send(embed=embed)

    # レベルシステムが有効かチェック
    level_system_enabled = config.get("level_system_enabled", True)
    if level_system_enabled and not message.author.bot:
        # メッセージ送信でXPを獲得（ランダムで15-25XP）
        xp_gain = random.randint(15, 25)
        leveled_up, new_level = add_xp(message.author.id, xp_gain)

        if leveled_up:
            # レベルアップ通知が有効な場合のみ送信
            levelup_notifications = config.get("levelup_notifications", True)
            if levelup_notifications:
                embed = discord.Embed(
                    title="🎉 レベルアップ！",
                    description=f"{message.author.mention} がレベル **{new_level}** に到達しました！",
                    color=discord.Color.gold()
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await message.channel.send(embed=embed)

    await bot.process_commands(message)



# 認証用のビュークラス
class VerificationView(discord.ui.View):
    def __init__(self, role: discord.Role):
        super().__init__(timeout=None)
        self.role = role

    @discord.ui.button(label="✅ 認証", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # 最初に応答を遅延させる（タイムアウト対策）
            await interaction.response.defer(ephemeral=True)

            # ロールが設定されていない場合（ボット再起動時など）
            if not self.role:
                await interaction.followup.send("❌ 認証設定にエラーがあります。管理者にお問い合わせください。", ephemeral=True)
                return
            # 既にロールを持っているかチェック
            if self.role in interaction.user.roles:
                await interaction.followup.send("✅ 既にこのロールを持っています。", ephemeral=True)
                return

            # ボットの権限を詳細チェック
            bot_member = interaction.guild.get_member(interaction.client.user.id)
            if not bot_member:
                await interaction.followup.send("❌ ボット情報を取得できませんでした。", ephemeral=True)
                return

            # ボットがロール管理権限を持っているかチェック
            if not bot_member.guild_permissions.manage_roles:
                await interaction.followup.send("❌ ボットに「ロールの管理」権限がありません。サーバー設定でボットにロール管理権限を付与してください。", ephemeral=True)
                return

            # ロールの位置をチェック
            if self.role.position >= bot_member.top_role.position:
                await interaction.followup.send(f"❌ ロール「{self.role.name}」はボットのロールよりも上位にあるため付与できません。\nボットのロールを「{self.role.name}」より上位に移動してください。", ephemeral=True)
                return

            # ボットがそのロールを付与できるかチェック
            if not bot_member.guild_permissions.administrator and self.role >= bot_member.top_role:
                await interaction.followup.send(f"❌ ボットはロール「{self.role.name}」を付与する権限がありません。", ephemeral=True)
                return

            # ロール付与を実行
            await interaction.user.add_roles(self.role, reason="認証による自動ロール付与")
            await interaction.followup.send(f"✅ 認証が完了しました！\n🎭 ロール「{self.role.name}」を付与しました。", ephemeral=True)

            # レベルシステムが有効な場合、認証ボーナスXPを付与
            level_system_enabled = config.get("level_system_enabled", True)
            if level_system_enabled:
                leveled_up, new_level = add_xp(interaction.user.id, 100)  # 認証ボーナス100XP
                if leveled_up:
                    await interaction.followup.send(f"🎉 認証ボーナス！レベル {new_level} に到達しました！", ephemeral=True)

        except discord.Forbidden as e:
            try:
                await interaction.followup.send(f"❌ 権限エラー: ボットにロール付与権限がありません。\n詳細: {str(e)}", ephemeral=True)
            except:
                pass
        except discord.HTTPException as e:
            try:
                await interaction.followup.send(f"❌ Discord APIエラーが発生しました。\n詳細: {str(e)}", ephemeral=True)
            except:
                pass
        except Exception as e:
            try:
                await interaction.followup.send(f"❌ 予期しないエラーが発生しました。\n詳細: {str(e)}", ephemeral=True)
            except:
                pass

# 認証コマンド
@bot.tree.command(name='verify', description='認証パネルをこのチャンネルに設置します')
@app_commands.describe(role='認証時に付与するロール名')
async def verify(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    bot_member = interaction.guild.get_member(bot.user.id)
    if not bot_member:
        await interaction.response.send_message("❌ ボット情報を取得できませんでした。", ephemeral=True)
        return

    # 詳細な権限チェック
    permissions_check = []

    # ロール管理権限チェック
    if not bot_member.guild_permissions.manage_roles:
        permissions_check.append("❌ ロールの管理権限がありません")
    else:
        permissions_check.append("✅ ロールの管理権限があります")

    # ロール階層チェック
    if role.position >= bot_member.top_role.position:
        permissions_check.append(f"❌ ロール「{role.name}」(位置: {role.position})はボットの最高ロール(位置: {bot_member.top_role.position})より上位です")
    else:
        permissions_check.append(f"✅ ロール階層は正常です")

    # @everyone ロールかチェック
    if role.is_default():
        permissions_check.append("❌ @everyoneロールは付与できません")

    # ボット自身のロールかチェック
    if role.managed:
        permissions_check.append("❌ 管理されたロール（ボットロールなど）は付与できません")

    # エラーがある場合は詳細を表示
    error_messages = [msg for msg in permissions_check if msg.startswith("❌")]
    if error_messages:
        embed = discord.Embed(
            title="❌ 認証パネル設置エラー",
            description="以下の問題を解決してから再度お試しください：",
            color=discord.Color.red()
        )
        embed.add_field(
            name="権限チェック結果",
            value="\n".join(permissions_check),
            inline=False
        )
        embed.add_field(
            name="🔧 解決方法",
            value="1. サーバー設定 → ロール → ボットのロールを選択\n"
                  "2. 「ロールの管理」権限を有効にする\n"
                  f"3. ボットのロールを「{role.name}」より上位に移動する",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # 成功時の埋め込みメッセージ
    embed = discord.Embed(
        title="🔐 認証パネル",
        description="下記のボタンを押して認証を完了してください",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="🎭 付与されるロール",
        value=role.mention,
        inline=True
    )
    embed.add_field(
        name="✅ 権限チェック",
        value="\n".join(permissions_check),
        inline=False
    )
    embed.add_field(
        name="🎁 認証後の特典",
        value="• サーバーへのフルアクセス\n• レベルシステム認証ボーナス (100XP)\n• 各種機能の利用",
        inline=False
    )
    embed.set_footer(text="認証は一人一回まで実行可能です")

    view = VerificationView(role)
    await interaction.response.send_message(embed=embed, view=view)

# チケットコマンド
@bot.tree.command(name="ticket_setup", description="チケットパネルを設置します")
@app_commands.describe(
    staff_role="チケット対応するスタッフロール",
    category="チケットを作成するカテゴリ",
    title="パネルのタイトル",
    description="パネルの説明"
)
async def ticket_setup(interaction: discord.Interaction, staff_role: discord.Role, category: discord.CategoryChannel, title: str = "🎫 サポートチケット", description: str = "サポートが必要な場合は、下のボタンをクリックしてチケットを作成してください。"):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📋 使用方法",
        value="1. 下の「🎫 チケット作成」ボタンをクリック\n2. 専用チャンネルが作成されます\n3. スタッフが対応します\n4. 問題解決後、チケットを削除します",
        inline=False
    )
    embed.add_field(
        name="👥 対応スタッフ",
        value=staff_role.mention,
        inline=True
    )
    embed.add_field(
        name="📁 作成場所",
        value=category.mention,
        inline=True
    )
    embed.set_footer(text="チケットは一人一つまで作成できます")

    view = TicketView(staff_role, category)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("チケットパネルを設置しました！", ephemeral=True)

@bot.tree.command(name="ticket_close", description="現在のチケットを強制的に削除します")
async def ticket_close(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("エラー: このコマンドを使用するにはメッセージ管理権限が必要です。", ephemeral=True)
        return

    # チケットチャンネルかどうかチェック
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("このコマンドはチケットチャンネルでのみ使用できます。", ephemeral=True)
        return

    await interaction.response.send_message("チケットを削除しています...", ephemeral=True)
    await interaction.channel.delete()

@bot.tree.command(name="ticket_list", description="現在開いているチケット一覧を表示します")
async def ticket_list(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("エラー: このコマンドを使用するにはメッセージ管理権限が必要です。", ephemeral=True)
        return

    # チケットチャンネルを検索
    ticket_channels = [ch for ch in interaction.guild.channels if ch.name.startswith("ticket-") and isinstance(ch, discord.TextChannel)]

    if not ticket_channels:
        await interaction.response.send_message("現在開いているチケットはありません。", ephemeral=True)
        return

    embed = discord.Embed(
        title="🎫 開いているチケット一覧",
        description=f"現在 **{len(ticket_channels)}個** のチケットが開いています",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )

    ticket_info = []
    for channel in ticket_channels[:10]:  # 最大10個まで表示
        # チャンネル作成日時を取得
        created_at = channel.created_at.strftime("%m/%d %H:%M")
        ticket_info.append(f"• {channel.mention} - 作成: {created_at}")

    embed.add_field(
        name="📋 チケット一覧",
        value="\n".join(ticket_info) if ticket_info else "なし",
        inline=False
    )

    if len(ticket_channels) > 10:
        embed.set_footer(text=f"他に {len(ticket_channels) - 10} 個のチケットがあります")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="timeout_config", description="自動タイムアウトの時間を設定します（分単位）")
async def timeout_config(interaction: discord.Interaction, minutes: int):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("エラー: このコマンドを使用するにはメッセージ管理権限が必要です。", ephemeral=True)
        return

    if minutes < 1 or minutes > 1440:  # 1分〜24時間の範囲
        await interaction.response.send_message("エラー: タイムアウト時間は1分〜1440分（24時間）の範囲で設定してください。", ephemeral=True)
        return

    # 設定をconfigファイルに保存
    config["timeout_minutes"] = minutes
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    embed = discord.Embed(
        title="⚙️ 設定完了",
        description=f"自動タイムアウト時間を **{minutes}分** に設定しました。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="backup", description="サーバーの情報をバックアップします")
async def backup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    backup_data = {
        "server_info": {
            "name": guild.name,
            "id": guild.id,
            "description": guild.description,
            "member_count": guild.member_count,
            "created_at": guild.created_at.isoformat(),
            "verification_level": str(guild.verification_level),
            "explicit_content_filter": str(guild.explicit_content_filter),
            "default_notifications": str(guild.default_notifications)
        },
        "channels": [],
        "categories": [],
        "roles": [],
        "members": [],
        "emojis": []
    }

    # カテゴリ情報
    for category in guild.categories:
        backup_data["categories"].append({
            "name": category.name,
            "id": category.id,
            "position": category.position
        })

    # チャンネル情報
    for channel in guild.channels:
        if isinstance(channel, discord.TextChannel):
            backup_data["channels"].append({
                "name": channel.name,
                "id": channel.id,
                "type": "text",
                "topic": channel.topic,
                "position": channel.position,
                "category": channel.category.name if channel.category else None,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay
            })
        elif isinstance(channel, discord.VoiceChannel):
            backup_data["channels"].append({
                "name": channel.name,
                "id": channel.id,
                "type": "voice",
                "position": channel.position,
                "category": channel.category.name if channel.category else None,
                "user_limit": channel.user_limit,
                "bitrate": channel.bitrate
            })

    # ロール情報
    for role in guild.roles:
        if role.name != "@everyone":
            backup_data["roles"].append({
                "name": role.name,
                "id": role.id,
                "color": str(role.color),
                "position": role.position,
                "permissions": role.permissions.value,
                "mentionable": role.mentionable,
                "hoist": role.hoist
            })

    # メンバー情報（基本情報のみ）
    for member in guild.members:
        if not member.bot:
            backup_data["members"].append({
                "name": member.name,
                "id": member.id,
                "display_name": member.display_name,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                "roles": [role.name for role in member.roles if role.name != "@everyone"]
            })

    # 絵文字情報
    for emoji in guild.emojis:
        backup_data["emojis"].append({
            "name": emoji.name,
            "id": emoji.id,
            "animated": emoji.animated,
            "url": str(emoji.url)
        })

    # バックアップファイルを保存
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{guild.name}_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)

    # バックアップ完了メッセージ
    embed = discord.Embed(
        title="バックアップ完了",
        description=f"サーバー「{guild.name}」のバックアップが完了しました。\n\n"
                   f"**ファイル名:** {filename}\n"
                   f"**チャンネル数:** {len(backup_data['channels'])}\n"
                   f"**ロール数:** {len(backup_data['roles'])}\n"
                   f"**メンバー数:** {len(backup_data['members'])}\n"
                   f"**絵文字数:** {len(backup_data['emojis'])}",
        color=discord.Color.green()
    )

    try:
        with open(filename, "rb") as f:
            file = discord.File(f, filename)
        await interaction.followup.send(embed=embed, file=file, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"バックアップは完成しましたが、ファイル送信でエラーが発生しました: {e}", ephemeral=True)

class EmbedModal(discord.ui.Modal, title="Embed作成"):
    def __init__(self):
        super().__init__()
        self.add_item(discord.ui.TextInput(label="タイトル", custom_id="title", required=True, max_length=256))
        self.add_item(discord.ui.TextInput(label="説明", custom_id="description", style=discord.TextStyle.paragraph, required=True, max_length=4000))
        self.add_item(discord.ui.TextInput(label="色（16進数 例: #ff0000）", custom_id="color", required=False, max_length=7, placeholder="#3498db"))
        self.add_item(discord.ui.TextInput(label="画像URL（任意）", custom_id="image", required=False, max_length=2000, placeholder="https://example.com/image.png"))
        self.add_item(discord.ui.TextInput(label="フッター（任意）", custom_id="footer", required=False, max_length=2048))

    async def on_submit(self, interaction: discord.Interaction):
        title = self.children[0].value
        description = self.children[1].value
        color_input = self.children[2].value
        image_url = self.children[3].value
        footer_text = self.children[4].value

        # 色の処理
        try:
            if color_input:
                if color_input.startswith('#'):
                    color = discord.Color(int(color_input[1:], 16))
                else:
                    color = discord.Color(int(color_input, 16))
            else:
                color = discord.Color.blue()
        except ValueError:
            color = discord.Color.blue()

        # Embed作成
        embed = discord.Embed(title=title, description=description, color=color)

        if image_url:
            try:
                embed.set_image(url=image_url)
            except:
                pass

        if footer_text:
            embed.set_footer(text=footer_text)

        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="embed", description="カスタムembedメッセージを作成します")
async def embed_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("エラー: このコマンドを使用するにはメッセージ管理権限が必要です。", ephemeral=True)
        return

    await interaction.response.send_modal(EmbedModal())

@bot.tree.command(name="log_channel", description="入退室ログを送信するチャンネルを設定します")
async def log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    # 設定をconfigファイルに保存
    config["log_channel_id"] = channel.id
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    embed = discord.Embed(
        title="⚙️ ログチャンネル設定完了",
        description=f"入退室ログを {channel.mention} に送信するように設定しました。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="welcome_toggle", description="DMウェルカムメッセージの有効/無効を切り替えます")
async def welcome_toggle(interaction: discord.Interaction, enabled: bool):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    # 設定をconfigファイルに保存
    config["welcome_dm_enabled"] = enabled
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    status = "有効" if enabled else "無効"
    embed = discord.Embed(
        title="⚙️ ウェルカムメッセージ設定完了",
        description=f"DMウェルカムメッセージを **{status}** にしました。",
        color=discord.Color.green() if enabled else discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="anti_spam_toggle", description="荒らし対策機能の有効/無効を切り替えます")
async def anti_spam_toggle(interaction: discord.Interaction, enabled: bool):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    config["anti_spam_enabled"] = enabled
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    status = "有効" if enabled else "無効"
    embed = discord.Embed(
        title="🛡️ 荒らし対策設定完了",
        description=f"荒らし対策機能を **{status}** にしました。",
        color=discord.Color.green() if enabled else discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="account_age_limit", description="新規アカウントの最小日数制限を設定します")
async def account_age_limit(interaction: discord.Interaction, days: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    if days < 0 or days > 365:
        await interaction.response.send_message("エラー: 日数は0〜365の範囲で設定してください。", ephemeral=True)
        return

    config["min_account_age_days"] = days
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    embed = discord.Embed(
        title="🛡️ アカウント制限設定完了",
        description=f"新規アカウント制限を **{days}日** に設定しました。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="bad_words_add", description="不適切な単語を追加します")
async def bad_words_add(interaction: discord.Interaction, word: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    bad_words = config.get("bad_words", [])
    if word.lower() not in [w.lower() for w in bad_words]:
        bad_words.append(word)
        config["bad_words"] = bad_words
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        embed = discord.Embed(
            title="🚫 不適切な単語追加完了",
            description=f"「{word}」を不適切な単語リストに追加しました。",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="⚠️ 既に登録済み",
            description=f"「{word}」は既に不適切な単語リストに登録されています。",
            color=discord.Color.orange()
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="bad_words_remove", description="不適切な単語を削除します")
async def bad_words_remove(interaction: discord.Interaction, word: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    bad_words = config.get("bad_words", [])
    original_count = len(bad_words)
    bad_words = [w for w in bad_words if w.lower() != word.lower()]

    if len(bad_words) < original_count:
        config["bad_words"] = bad_words
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        embed = discord.Embed(
            title="🚫 不適切な単語削除完了",
            description=f"「{word}」を不適切な単語リストから削除しました。",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="⚠️ 単語が見つかりません",
            description=f"「{word}」は不適切な単語リストに登録されていません。",
            color=discord.Color.orange()
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="moderation_status", description="荒らし対策機能の現在の設定を表示します")
async def moderation_status(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("エラー: このコマンドを使用するにはメッセージ管理権限が必要です。", ephemeral=True)
        return

    anti_spam = "✅ 有効" if config.get("anti_spam_enabled", True) else "❌ 無効"
    account_age = config.get("min_account_age_days", 7)
    timeout_minutes = config.get("timeout_minutes", 10)
    bad_words_count = len(config.get("bad_words", []))

    embed = discord.Embed(
        title="🛡️ 荒らし対策機能の状態",
        color=discord.Color.blue()
    )
    embed.add_field(name="荒らし対策機能", value=anti_spam, inline=True)
    embed.add_field(name="新規アカウント制限", value=f"{account_age}日", inline=True)
    embed.add_field(name="メンションタイムアウト", value=f"{timeout_minutes}分", inline=True)
    embed.add_field(name="不適切な単語数", value=f"{bad_words_count}個", inline=True)
    embed.add_field(name="警告中のユーザー", value=f"{len(spam_warnings)}人", inline=True)
    embed.set_footer(text="設定変更は各コマンドで行えます")

    await interaction.response.send_message(embed=embed, ephemeral=True)

# 権限チェック関数
def check_command_permission(user_id: int) -> bool:
    """コマンド使用権限をチェックする関数"""
    allowed_users = config.get("allowed_command_users", [])
    bot_owner_id = config.get("bot_owner_id")

    # Bot所有者は常に使用可能
    if bot_owner_id and user_id == bot_owner_id:
        return True

    # 許可されたユーザーリストに含まれているかチェック
    return user_id in allowed_users

@bot.tree.command(name="set_bot_owner", description="Bot所有者を設定します（初回のみ）")
async def set_bot_owner(interaction: discord.Interaction):
    # 既に所有者が設定されている場合はエラー
    if config.get("bot_owner_id"):
        await interaction.response.send_message("❌ Bot所有者は既に設定されています。", ephemeral=True)
        return

    # 初回設定として現在のユーザーを所有者に設定
    config["bot_owner_id"] = interaction.user.id
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    embed = discord.Embed(
        title="👑 Bot所有者設定完了",
        description=f"{interaction.user.mention} をBot所有者として設定しました。",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="add_command_user", description="Botコマンドの使用を許可するユーザーを追加します")
async def add_command_user(interaction: discord.Interaction, user: discord.Member):
    # Bot所有者のみ実行可能
    bot_owner_id = config.get("bot_owner_id")
    if not bot_owner_id or interaction.user.id != bot_owner_id:
        await interaction.response.send_message("❌ このコマンドはBot所有者のみ使用できます。", ephemeral=True)
        return

    allowed_users = config.get("allowed_command_users", [])

    if user.id in allowed_users:
        await interaction.response.send_message(f"⚠️ {user.mention} は既に許可されています。", ephemeral=True)
        return

    allowed_users.append(user.id)
    config["allowed_command_users"] = allowed_users
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    embed = discord.Embed(
        title="✅ ユーザー追加完了",
        description=f"{user.mention} にBotコマンドの使用権限を付与しました。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove_command_user", description="Botコマンドの使用許可を取り消します")
async def remove_command_user(interaction: discord.Interaction, user: discord.Member):
    # Bot所有者のみ実行可能
    bot_owner_id = config.get("bot_owner_id")
    if not bot_owner_id or interaction.user.id != bot_owner_id:
        await interaction.response.send_message("❌ このコマンドはBot所有者のみ使用できます。", ephemeral=True)
        return

    allowed_users = config.get("allowed_command_users", [])

    if user.id not in allowed_users:
        await interaction.response.send_message(f"⚠️ {user.mention} は許可リストに含まれていません。", ephemeral=True)
        return

    allowed_users.remove(user.id)
    config["allowed_command_users"] = allowed_users
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    embed = discord.Embed(
        title="🚫 ユーザー削除完了",
        description=f"{user.mention} のBotコマンド使用権限を取り消しました。",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="list_command_users", description="Botコマンドの使用が許可されているユーザー一覧を表示します")
async def list_command_users(interaction: discord.Interaction):
    # Bot所有者のみ実行可能
    bot_owner_id = config.get("bot_owner_id")
    if not bot_owner_id or interaction.user.id != bot_owner_id:
        await interaction.response.send_message("❌ このコマンドはBot所有者のみ使用できます。", ephemeral=True)
        return

    allowed_users = config.get("allowed_command_users", [])

    embed = discord.Embed(
        title="📋 Botコマンド使用許可ユーザー一覧",
        color=discord.Color.blue()
    )

    # Bot所有者情報
    bot_owner = bot.get_user(bot_owner_id)
    owner_name = bot_owner.name if bot_owner else f"ID: {bot_owner_id}"
    embed.add_field(name="👑 Bot所有者", value=owner_name, inline=False)

    # 許可されたユーザー一覧
    if allowed_users:
        user_list = []
        for user_id in allowed_users:
            user = bot.get_user(user_id)
            user_name = user.name if user else f"ID: {user_id}"
            user_list.append(user_name)

        embed.add_field(
            name="✅ 許可されたユーザー",
            value="\n".join(user_list) if user_list else "なし",
            inline=False
        )
    else:
        embed.add_field(name="✅ 許可されたユーザー", value="なし", inline=False)

    embed.set_footer(text=f"総数: {len(allowed_users) + 1}人")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="chat", description="AIと会話します")
@app_commands.describe(message="AIに送信するメッセージ")
async def chat(interaction: discord.Interaction, message: str):
    if not check_command_permission(interaction.user.id):
        await interaction.response.send_message("❌ このコマンドを使用する権限がありません。", ephemeral=True)
        return

    if not openai_client:
        await interaction.response.send_message("❌ OpenAI APIが設定されていません。", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "あなたは親しみやすくて役立つアシスタントです。日本語で回答してください。"},
                {"role": "user", "content": message}
            ],
            max_tokens=1000,
            temperature=0.7
        )

        ai_response = response.choices[0].message.content

        embed = discord.Embed(
            title="🤖 AI Chat",
            description=ai_response,
            color=discord.Color.blue()
        )
        embed.add_field(name="質問", value=message, inline=False)
        embed.set_footer(text=f"質問者: {interaction.user.display_name}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        error_embed = discord.Embed(
            title="❌ エラー",
            description=f"AI応答の生成中にエラーが発生しました: {str(e)}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.tree.command(name="translate", description="テキストを翻訳します")
@app_commands.describe(
    text="翻訳するテキスト",
    target_language="翻訳先の言語（例: EN, JA, KO, ZH, FR, DE, ES）"
)
async def translate(interaction: discord.Interaction, text: str, target_language: str):
    if not check_command_permission(interaction.user.id):
        await interaction.response.send_message("❌ このコマンドを使用する権限がありません。", ephemeral=True)
        return

    if not deepl_translator:
        await interaction.response.send_message("❌ DeepL APIが設定されていません。", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        # 言語コードを大文字に変換
        target_lang = target_language.upper()

        # 翻訳実行
        result = deepl_translator.translate_text(text, target_lang=target_lang)

        embed = discord.Embed(
            title="🌐 翻訳結果",
            color=discord.Color.green()
        )
        embed.add_field(name="原文", value=text, inline=False)
        embed.add_field(name=f"翻訳結果 ({result.detected_source_lang} → {target_lang})", value=result.text, inline=False)
        embed.set_footer(text=f"翻訳者: {interaction.user.display_name}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        error_embed = discord.Embed(
            title="❌ 翻訳エラー",
            description=f"翻訳中にエラーが発生しました: {str(e)}",
            color=discord.Color.red()
        )
        error_embed.add_field(
            name="サポートされている言語",
            value="EN (英語), JA (日本語), KO (韓国語), ZH (中国語), FR (フランス語), DE (ドイツ語), ES (スペイン語) など",
            inline=False
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.tree.command(name="achievement_report", description="指定したチャンネルの実績評価と内容を送信します")
@app_commands.describe(channel="実績を収集するチャンネル", limit="取得するメッセージ数（デフォルト：50）")
async def achievement_report(interaction: discord.Interaction, channel: discord.TextChannel, limit: int = 50):
    if not check_command_permission(interaction.user.id):
        await interaction.response.send_message("❌ このコマンドを使用する権限がありません。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("エラー: このコマンドを使用するにはメッセージ管理権限が必要です。", ephemeral=True)
        return

    if limit < 1 or limit > 100:
        await interaction.response.send_message("エラー: メッセージ数は1〜100の範囲で指定してください。", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        # チャンネルからメッセージを取得
        messages = []
        async for message in channel.history(limit=limit):
            if not message.author.bot and message.content.strip():
                messages.append(message)

        if not messages:
            await interaction.followup.send("指定されたチャンネルに実績メッセージが見つかりませんでした。", ephemeral=True)
            return

        # 実績評価レポートを作成
        embed = discord.Embed(
            title=f"🏆 実績評価レポート - {channel.name}",
            description=f"取得期間: 最新{len(messages)}件のメッセージ",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        # メッセージ統計
        user_stats = {}
        total_characters = 0

        for msg in messages:
            user_id = msg.author.id
            if user_id not in user_stats:
                user_stats[user_id] = {
                    "user": msg.author,
                    "count": 0,
                    "characters": 0,
                    "reactions": 0
                }

            user_stats[user_id]["count"] += 1
            user_stats[user_id]["characters"] += len(msg.content)
            user_stats[user_id]["reactions"] += sum(reaction.count for reaction in msg.reactions)
            total_characters += len(msg.content)

        # トップ貢献者
        top_contributors = sorted(user_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:5]

        contributors_text = ""
        for i, (user_id, stats) in enumerate(top_contributors, 1):
            contributors_text += f"{i}. {stats['user'].display_name}: {stats['count']}件\n"
            contributors_text += f"   文字数: {stats['characters']}文字 | リアクション: {stats['reactions']}個\n"

        embed.add_field(
            name="📊 トップ貢献者",
            value=contributors_text if contributors_text else "データなし",
            inline=False
        )

        # 全体統計
        embed.add_field(
            name="📈 全体統計",
            value=f"**総メッセージ数:** {len(messages)}件\n"
                  f"**総文字数:** {total_characters:,}文字\n"
                  f"**平均文字数:** {total_characters // len(messages) if messages else 0}文字/メッセージ\n"
                  f"**参加ユーザー数:** {len(user_stats)}人",
            inline=False
        )

        # 最新の実績内容（上位3件）
        recent_achievements = messages[:3]
        recent_text = ""
        for i, msg in enumerate(recent_achievements, 1):
            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            recent_text += f"**{i}.** {msg.author.display_name}\n"
            recent_text += f"```{content}```\n"

        if recent_text:
            embed.add_field(
                name="🆕 最新の実績内容",
                value=recent_text,
                inline=False
            )

        # 評価コメント
        if len(messages) >= 20:
            evaluation = "📈 非常に活発なチャンネルです！"
        elif len(messages) >= 10:
            evaluation = "📊 適度な活動があります。"
        else:
            evaluation = "📉 もう少し活動を促進してみましょう。"

        embed.add_field(
            name="💭 総合評価",
            value=evaluation,
            inline=False
        )

        embed.set_footer(text=f"レポート作成者: {interaction.user.display_name}")
        embed.set_thumbnail(url=channel.guild.icon.url if channel.guild.icon else None)

        await interaction.followup.send(embed=embed)

    except discord.Forbidden:
        await interaction.followup.send("❌ 指定されたチャンネルへのアクセス権限がありません。", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)

class AchievementModal(discord.ui.Modal, title="実績報告"):
    def __init__(self, target_channel: discord.TextChannel):
        super().__init__()
        self.target_channel = target_channel

        self.add_item(discord.ui.TextInput(
            label="実績タイトル",
            custom_id="title",
            required=True,
            max_length=100,
            placeholder="例: プロジェクト完成、目標達成など"
        ))

        self.add_item(discord.ui.TextInput(
            label="実績内容詳細",
            custom_id="content",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
            placeholder="実績の詳細な内容を記入してください..."
        ))

        self.add_item(discord.ui.TextInput(
            label="自己評価 (1-10)",
            custom_id="self_rating",
            required=True,
            max_length=2,
            placeholder="1-10の数値で自己評価"
        ))

        self.add_item(discord.ui.TextInput(
            label="難易度 (1-10)",
            custom_id="difficulty",
            required=True,
            max_length=2,
            placeholder="1-10の数値で難易度評価"
        ))

        self.add_item(discord.ui.TextInput(
            label="追加コメント",
            custom_id="comment",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            placeholder="感想や今後の目標など（任意）"
        ))

    async def on_submit(self, interaction: discord.Interaction):
        title = self.children[0].value
        content = self.children[1].value
        self_rating_str = self.children[2].value
        difficulty_str = self.children[3].value
        comment = self.children[4].value

        # 評価の数値チェック
        try:
            self_rating = int(self_rating_str)
            difficulty = int(difficulty_str)

            if not (1 <= self_rating <= 10) or not (1 <= difficulty <= 10):
                await interaction.response.send_message("❌ 評価と難易度は1-10の範囲で入力してください。", ephemeral=True)
                return

        except ValueError:
            await interaction.response.send_message("❌ 評価と難易度は数値で入力してください。", ephemeral=True)
            return

        # 評価に基づく色の決定
        if self_rating >= 8:
            color = discord.Color.gold()
            rating_emoji = "🏆"
        elif self_rating >= 6:
            color = discord.Color.green()
            rating_emoji = "🥈"
        elif self_rating >= 4:
            color = discord.Color.orange()
            rating_emoji = "🥉"
        else:
            color = discord.Color.red()
            rating_emoji = "📝"

        # 難易度に基づく絵文字
        if difficulty >= 8:
            difficulty_emoji = "🔥🔥🔥"
        elif difficulty >= 6:
            difficulty_emoji = "🔥🔥"
        elif difficulty >= 4:
            difficulty_emoji = "🔥"
        else:
            difficulty_emoji = "⭐"

        # 実績レポート埋め込みメッセージ作成
        embed = discord.Embed(
            title=f"{rating_emoji} {title}",
            description=content,
            color=color,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="📊 評価",
            value=f"**自己評価:** {self_rating}/10 {rating_emoji}\n**難易度:** {difficulty}/10 {difficulty_emoji}",
            inline=True
        )

        embed.add_field(
            name="👤 報告者",
            value=interaction.user.display_name,
            inline=True
        )

        # 総合スコア計算
        total_score = (self_rating + difficulty) / 2
        embed.add_field(
            name="🎯 総合スコア",
            value=f"{total_score:.1f}/10",
            inline=True
        )

        if comment:
            embed.add_field(
                name="💭 追加コメント",
                value=comment,
                inline=False
            )

        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"報告日時: {discord.utils.utcnow().strftime('%Y年%m月%d日 %H:%M:%S')}")

        try:
            # 指定チャンネルに送信
            await self.target_channel.send(embed=embed)

            # レベルシステムが有効な場合、XPを付与
            level_system_enabled = config.get("level_system_enabled", True)
            if level_system_enabled:
                # 評価に基づいてXPを計算 (高い評価ほど多くのXP)
                xp_bonus = self_rating * 10 + difficulty * 5
                leveled_up, new_level = add_xp(interaction.user.id, xp_bonus)

                success_message = f"✅ 実績を {self.target_channel.mention} に送信しました！\n🎁 {xp_bonus}XPを獲得しました！"

                if leveled_up:
                    success_message += f"\n🎉 レベルアップ！新しいレベル: {new_level}"
            else:
                success_message = f"✅ 実績を {self.target_channel.mention} に送信しました！"

            await interaction.response.send_message(success_message, ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message("❌ 指定されたチャンネルへの送信権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)

@bot.tree.command(name="achievement_setup", description="実績報告パネルを設置します")
@app_commands.describe(target_channel="実績を送信するチャンネル", title="パネルのタイトル", description="パネルの説明")
async def achievement_setup(interaction: discord.Interaction, target_channel: discord.TextChannel, title: str = "実績報告", description: str = "下のボタンから実績を報告してください"):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("エラー: このコマンドを使用するにはメッセージ管理権限が必要です。", ephemeral=True)
        return

    # パネル用埋め込みメッセージ
    embed = discord.Embed(
        title=f"🏆 {title}",
        description=description,
        color=discord.Color.blue()
    )

    embed.add_field(
        name="📝 報告方法",
        value="1. 下の「実績を報告する」ボタンをクリック\n2. フォームに実績内容を記入\n3. 自己評価と難易度を入力\n4. 送信完了！",
        inline=False
    )

    embed.add_field(
        name="📊 評価基準",
        value="**自己評価:** あなたの達成感や満足度\n**難易度:** その実績の困難さや挑戦度\n(1=簡単/低い ↔ 10=困難/高い)",
        inline=False
    )

    embed.add_field(
        name="🎯 送信先",
        value=target_channel.mention,
        inline=True
    )

    embed.set_footer(text="実績を共有して、みんなで成長を祝いましょう！")

    # ボタンビュー作成
    class AchievementView(discord.ui.View):
        def __init__(self, target_channel: discord.TextChannel):
            super().__init__(timeout=None)
            self.target_channel = target_channel

        @discord.ui.button(label="🏆 実績を報告する", style=discord.ButtonStyle.primary, custom_id="achievement_report_btn")
        async def report_achievement(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = AchievementModal(self.target_channel)
            await interaction.response.send_modal(modal)

    view = AchievementView(target_channel)
    await interaction.channel.send(embed=embed, view=view)

    await interaction.response.send_message(f"✅ 実績報告パネルを設置しました！送信先: {target_channel.mention}", ephemeral=True)

# レベルシステム関連コマンド
@bot.tree.command(name="level", description="自分または指定したユーザーのレベル情報を表示します")
@app_commands.describe(user="レベルを確認したいユーザー（省略時は自分）")
async def level(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user

    level_data = load_level_data()
    user_id = str(target_user.id)

    if user_id not in level_data:
        level_data[user_id] = {"level": 1, "xp": 0}
        save_level_data(level_data)

    user_level = level_data[user_id]["level"]
    user_xp = level_data[user_id]["xp"]
    xp_needed = calculate_xp_needed(user_level)

    # プログレスバー作成
    progress = user_xp / xp_needed
    progress_bar_length = 20
    filled_length = int(progress_bar_length * progress)
    bar = "█" * filled_length + "░" * (progress_bar_length - filled_length)

    embed = discord.Embed(
        title=f"📊 {target_user.display_name} のレベル情報",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🎯 現在のレベル",
        value=f"**レベル {user_level}**",
        inline=True
    )

    embed.add_field(
        name="⭐ 経験値",
        value=f"{user_xp:,} / {xp_needed:,} XP",
        inline=True
    )

    embed.add_field(
        name="📈 進行状況",
        value=f"`{bar}` {progress:.1%}",
        inline=False
    )

    # 次のレベルまでの必要XP
    xp_remaining = xp_needed - user_xp
    embed.add_field(
        name="🎪 次のレベルまで",
        value=f"{xp_remaining:,} XP",
        inline=True
    )

    # 総XP計算
    total_xp = sum(calculate_xp_needed(i) for i in range(1, user_level)) + user_xp
    embed.add_field(
        name="🏆 総経験値",
        value=f"{total_xp:,} XP",
        inline=True
    )

    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.set_footer(text="メッセージ送信や実績報告でXPを獲得できます！")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="サーバーのレベルランキングを表示します")
@app_commands.describe(limit="表示する人数（デフォルト：10人）")
async def leaderboard(interaction: discord.Interaction, limit: int = 10):
    if limit < 1 or limit > 20:
        await interaction.response.send_message("❌ 表示人数は1〜20人の範囲で指定してください。", ephemeral=True)
        return

    level_data = load_level_data()

    if not level_data:
        await interaction.response.send_message("❌ レベルデータが見つかりません。", ephemeral=True)
        return

    # 総XPでソート
    user_scores = []
    for user_id, data in level_data.items():
        user = interaction.guild.get_member(int(user_id))
        if user and not user.bot:
            level = data["level"]
            current_xp = data["xp"]
            total_xp = sum(calculate_xp_needed(i) for i in range(1, level)) + current_xp
            user_scores.append((user, level, total_xp))

    # 総XPでソート
    user_scores.sort(key=lambda x: x[2], reverse=True)

    embed = discord.Embed(
        title="🏆 レベルランキング",
        description=f"トップ {min(limit, len(user_scores))} 人",
        color=discord.Color.gold()
    )

    rank_emojis = ["🥇", "🥈", "🥉"]

    leaderboard_text = ""
    for i, (user, level, total_xp) in enumerate(user_scores[:limit]):
        rank = i + 1
        if rank <= 3:
            emoji = rank_emojis[rank - 1]
        else:
            emoji = f"{rank}."

        leaderboard_text += f"{emoji} **{user.display_name}**\n"
        leaderboard_text += f"    レベル {level} - {total_xp:,} XP\n\n"

    if leaderboard_text:
        embed.add_field(
            name="📊 ランキング",
            value=leaderboard_text,
            inline=False
        )
    else:
        embed.add_field(
            name="📊 ランキング",
            value="データがありません",
            inline=False
        )

    # 自分の順位を表示
    user_rank = None
    for i, (user, level, total_xp) in enumerate(user_scores):
        if user.id == interaction.user.id:
            user_rank = i + 1
            break

    if user_rank:
        embed.add_field(
            name="🎯 あなたの順位",
            value=f"{user_rank}位 / {len(user_scores)}人",
            inline=True
        )

    embed.set_footer(text=f"総参加者数: {len(user_scores)}人")
    embed.timestamp = discord.utils.utcnow()

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="level_config", description="レベルシステムの設定を変更します")
@app_commands.describe(
    enabled="レベルシステムを有効にするか",
    notifications="レベルアップ通知を有効にするか"
)
async def level_config(interaction: discord.Interaction, enabled: bool = None, notifications: bool = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    changes = []

    if enabled is not None:
        config["level_system_enabled"] = enabled
        status = "有効" if enabled else "無効"
        changes.append(f"レベルシステム: **{status}**")

    if notifications is not None:
        config["levelup_notifications"] = notifications
        status = "有効" if notifications else "無効"
        changes.append(f"レベルアップ通知: **{status}**")

    if not changes:
        # 現在の設定を表示
        level_enabled = config.get("level_system_enabled", True)
        notif_enabled = config.get("levelup_notifications", True)

        embed = discord.Embed(
            title="⚙️ レベルシステム設定",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📊 レベルシステム",
            value="✅ 有効" if level_enabled else "❌ 無効",
            inline=True
        )
        embed.add_field(
            name="🔔 レベルアップ通知",
            value="✅ 有効" if notif_enabled else "❌ 無効",
            inline=True
        )
        embed.set_footer(text="設定を変更するには引数を指定してください")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # 設定を保存
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    embed = discord.Embed(
        title="⚙️ レベルシステム設定変更完了",
        description="\n".join(changes),
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="add_xp", description="指定したユーザーにXPを付与します（管理者のみ）")
@app_commands.describe(user="XPを付与するユーザー", amount="付与するXP量")
async def add_xp_command(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
        return

    if amount < 1 or amount > 10000:
        await interaction.response.send_message("❌ XP量は1〜10000の範囲で指定してください。", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message("❌ Botにはレベルシステムは適用されません。", ephemeral=True)
        return

    # XPを付与
    leveled_up, new_level = add_xp(user.id, amount)

    embed = discord.Embed(
        title="🎁 XP付与完了",
        description=f"{user.mention} に **{amount:,}XP** を付与しました。",
        color=discord.Color.green()
    )

    if leveled_up:
        embed.add_field(
            name="🎉 レベルアップ！",
            value=f"新しいレベル: **{new_level}**",
            inline=True
        )
        embed.color = discord.Color.gold()

    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=f"実行者: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="nuke", description="現在のチャンネルを削除し、同じ設定のチャンネルを再作成します。")
async def nuke(interaction: discord.Interaction):
    if not check_command_permission(interaction.user.id):
        await interaction.response.send_message("❌ このコマンドを使用する権限がありません。", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
         await interaction.response.send_message("エラー: このコマンドを使用するには管理者権限が必要です。", ephemeral=True)
         return 

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("エラー: このコマンドはテキストチャンネルでのみ使用できます。", ephemeral=True)
        return

    channel_name = channel.name
    channel_topic = channel.topic
    channel_position = channel.position
    channel_category = channel.category
    overwrites = channel.overwrites

    await interaction.response.send_message(f"チャンネル「{channel_name}」をリセット中...", ephemeral=True)
    await channel.delete()

    new_channel = await channel_category.create_text_channel(
        name=channel_name,
        topic=channel_topic,
        overwrites=overwrites,
        position=channel_position
    )

    media_urls = [
        "https://media.tenor.com/HUHWgsKCJ0oAAAAM/gear-5-gear-5-luffy.gif",
        "https://cdn-ak.f.st-hatena.com/images/fotolife/m/mtmblgsn/20160205/20160205054036.gif"
    ]
    selected_url = random.choice(media_urls)

    embed = discord.Embed(
        title="チャンネルリセット完了",
        description="このチャンネルはリセットされました。💣",
        color=discord.Color.red()
    )
    embed.set_image(url=selected_url)
    embed.set_footer(text="Made by 8j1u | Thx")

    await new_channel.send(embed=embed)

if __name__ == "__main__":
    # Renderでのポート設定
    port = int(os.getenv('PORT', 5000))
    
    # 簡単なウェブサーバーを追加（Renderがアプリが起動していることを確認するため）
    from threading import Thread
    import http.server
    import socketserver
    
    class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'Discord Bot is running!')
    
    def run_web_server():
        with socketserver.TCPServer(("0.0.0.0", port), MyHTTPRequestHandler) as httpd:
            print(f"Web server running on port {port}")
            httpd.serve_forever()
    
    # ウェブサーバーを別スレッドで起動
    web_thread = Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("エラー: DISCORD_TOKENが設定されていません。環境変数でトークンを設定してください。")
        print("Renderでは Environment Variables セクションで設定できます。")
    else:
        print("Discord Bot を起動中...")
        bot.run(token)
