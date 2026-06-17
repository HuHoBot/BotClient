# -*- coding: utf-8 -*-

from pathlib import Path

import aiosqlite
from ymbotpy import logging

DATABASE_PATH = "data/database.db"

_log = logging.get_logger()


class SQLiteSession:
    """管理单次仓储操作使用的异步 SQLite 连接。"""

    def __init__(self, db_path: str = DATABASE_PATH):
        """记录数据库路径，供后续连接时复用。"""
        self.db_path = db_path
        self.connection = None

    async def Connect(self):
        """打开当前会话对应的数据库连接。"""
        self.connection = await aiosqlite.connect(self.db_path)

    async def Close(self):
        """关闭当前会话连接，并清理连接引用。"""
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    async def Execute(self, query: str, params=None):
        """执行写入语句，并返回游标查询结果。"""
        if params is None:
            params = []
        async with self.connection.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def FetchOne(self, query: str, params=None):
        """执行查询语句，并返回第一条记录。"""
        if params is None:
            params = []
        async with self.connection.execute(query, params) as cursor:
            return await cursor.fetchone()

    async def FetchAll(self, query: str, params=None):
        """执行查询语句，并返回全部记录。"""
        if params is None:
            params = []
        async with self.connection.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def Commit(self):
        """提交当前事务。"""
        await self.connection.commit()

    async def Rollback(self):
        """回滚当前事务。"""
        await self.connection.rollback()


class PendingBindStore:
    """在内存中暂存待确认的绑定请求。"""

    def __init__(self):
        """初始化待确认绑定缓存。"""
        self._store = {}

    def AddRequest(self, request_id: str, server_id: str, group_id: str, author: str, is_multi_group: bool):
        """保存一条待服务端确认的绑定请求。"""
        self._store[request_id] = {
            "serverId": server_id,
            "groupId": group_id,
            "author": author,
            "isMoreGroup": is_multi_group,
        }
        return True

    def GetRequest(self, request_id: str):
        """按请求编号读取待确认绑定数据。"""
        return self._store.get(request_id)

    def RemoveRequest(self, request_id: str):
        """移除已经消费过的绑定请求。"""
        if request_id in self._store:
            del self._store[request_id]
            return True
        return False


async def InitDb():
    """初始化机器人运行所需的数据表。"""
    data_dir = Path(DATABASE_PATH).parent
    data_dir.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS bindServer (
                `group` TEXT NOT NULL,
                `serverId` TEXT NOT NULL,
                `hashKey` TEXT NOT NULL,
                `serverName` TEXT NOT NULL DEFAULT 'server',
                PRIMARY KEY (`group`, `serverId`)
            )
            """
        )
        # 迁移旧表结构
        cursor = await db.execute("PRAGMA table_info(bindServer)")
        columns = {row[1]: row[5] for row in await cursor.fetchall()}  # name -> pk
        # 1) 补 serverName 列
        if "serverName" not in columns:
            try:
                await db.execute(
                    "ALTER TABLE bindServer ADD COLUMN `serverName` TEXT NOT NULL DEFAULT 'server'"
                )
            except Exception:
                pass
        # 2) 旧单列主键 → 重建为组合主键
        if columns.get("serverId", 0) == 0:
            try:
                await db.execute(
                    """
                    CREATE TABLE bindServer_new (
                        `group` TEXT NOT NULL,
                        `serverId` TEXT NOT NULL,
                        `hashKey` TEXT NOT NULL,
                        `serverName` TEXT NOT NULL DEFAULT 'server',
                        PRIMARY KEY (`group`, `serverId`)
                    )
                    """
                )
                await db.execute(
                    "INSERT INTO bindServer_new (`group`, `serverId`, `hashKey`, `serverName`) "
                    "SELECT `group`, `serverId`, `hashKey`, `serverName` FROM bindServer"
                )
                await db.execute("DROP TABLE bindServer")
                await db.execute("ALTER TABLE bindServer_new RENAME TO bindServer")
            except Exception:
                await db.execute("DROP TABLE IF EXISTS bindServer_new")
                raise

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS adminList (
                `group` TEXT NOT NULL,
                `author` TEXT NOT NULL,
                PRIMARY KEY (`group`, `author`)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS nickName (
                `group` TEXT NOT NULL,
                `author` TEXT NOT NULL,
                `name` TEXT NOT NULL,
                `forceEdit` INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (`group`, `author`)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS blockMotd (
                `group` TEXT PRIMARY KEY
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS bindQQ (
                `groupId` TEXT NOT NULL,
                `openId` TEXT NOT NULL,
                `qq` TEXT NOT NULL,
                PRIMARY KEY (`groupId`, `openId`)
            )
            """
        )
        await db.commit()


class BindRepository:
    """负责管理群与服务器的绑定关系。"""

    def __init__(self, db_path: str = DATABASE_PATH):
        """记录仓储使用的数据库路径。"""
        self.db_path = db_path

    async def BindServer(self, group_id: str, config: dict):
        """写入或更新指定群的服务器绑定。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "INSERT OR REPLACE INTO bindServer (`group`, `serverId`, `hashKey`, `serverName`) VALUES (?, ?, ?, ?)",
                (group_id, config["serverId"], config["hashKey"], config.get("serverName", "server")),
            )
            await session.Commit()
        finally:
            await session.Close()

    async def GetByGroup(self, group_id: str) -> list[str]:
        """按群号读取绑定记录，不存在时返回 `[]`。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            rows = await session.FetchAll(
                "SELECT `group`, `serverId` FROM bindServer WHERE `group` = ?",
                (group_id,),
            )
        finally:
            await session.Close()
        if rows:
            return rows
        return []

    async def GetByServerId(self, server_id: str):
        """按服务器编号读取所有绑定记录。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            return await session.FetchAll(
                "SELECT `group`, `serverId`, `hashKey` FROM bindServer WHERE `serverId` = ?",
                (server_id,),
            )
        finally:
            await session.Close()

    async def GetHashKeyByServerId(self, server_id: str):
        """按服务器编号读取绑定时保存的哈希密钥。"""
        rows = await self.GetByServerId(server_id)
        if rows:
            return rows[0][2]
        return None

    async def SetServerName(self, group_id: str, server_id: str, server_name: str) -> bool:
        """设置指定绑定记录的服务器名称。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "UPDATE bindServer SET `serverName` = ? WHERE `group` = ? AND `serverId` = ?",
                (server_name, group_id, server_id),
            )
            await session.Commit()
            return True
        except Exception as exc:
            _log.error(f"设置服务器名称失败: {exc}")
            return False
        finally:
            await session.Close()

    async def GetServerName(self, group_id: str, server_id: str):
        """读取指定绑定记录的服务器名称，不存在时返回 None。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            row = await session.FetchOne(
                "SELECT `serverName` FROM bindServer WHERE `group` = ? AND `serverId` = ?",
                (group_id, server_id),
            )
        finally:
            await session.Close()
        if row:
            return row[0]
        return None

    async def DeleteServerName(self, group_id: str, server_id: str) -> bool:
        """重置指定绑定记录的服务器名称为默认值。"""
        return await self.SetServerName(group_id, server_id, "server")

    async def UnbindServer(self, group_id: str, server_id: str) -> bool:
        """删除指定群与指定服务器的绑定记录。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "DELETE FROM bindServer WHERE `group` = ? AND `serverId` = ?",
                (group_id, server_id),
            )
            await session.Commit()
            return True
        except Exception as exc:
            _log.error(f"解绑服务器失败: {exc}")
            return False
        finally:
            await session.Close()


class AdminRepository:
    """负责管理群管理员名单。"""

    def __init__(self, db_path: str = DATABASE_PATH):
        """记录仓储使用的数据库路径。"""
        self.db_path = db_path

    async def IsAdmin(self, group_id: str, author: str) -> bool:
        """判断指定成员是否为当前群管理员。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            rows = await session.FetchAll(
                "SELECT 1 FROM adminList WHERE `group` = ? AND `author` = ?",
                (group_id, author),
            )
        finally:
            await session.Close()
        return len(rows) > 0

    async def AddAdmin(self, group_id: str, author: str):
        """为群添加一名管理员。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "INSERT OR REPLACE INTO adminList (`group`, `author`) VALUES (?, ?)",
                (group_id, author),
            )
            await session.Commit()
        finally:
            await session.Close()
        return True

    async def RemoveAdmin(self, group_id: str, author: str):
        """从群管理员名单中移除一名成员。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "DELETE FROM adminList WHERE `group` = ? AND `author` = ?",
                (group_id, author),
            )
            await session.Commit()
        finally:
            await session.Close()
        return True


class NicknameRepository:
    """负责管理群服互通昵称。"""

    def __init__(self, db_path: str = DATABASE_PATH):
        """记录仓储使用的数据库路径。"""
        self.db_path = db_path

    async def GetName(self, group_id: str, author: str):
        """读取成员在当前群中的绑定昵称。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            rows = await session.FetchAll(
                "SELECT `name` FROM nickName WHERE `group` = ? AND `author` = ?",
                (group_id, author),
            )
        finally:
            await session.Close()
        if rows:
            return rows[0][0]
        return None

    async def SetName(
        self,
        group_id: str,
        author: str,
        nickname: str,
        force_edit=False,
        change_status=False,
    ) -> bool:
        """写入昵称，并处理重名和锁定状态校验。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            other_user = await session.FetchOne(
                "SELECT 1 FROM nickName WHERE `group` = ? AND LOWER(`name`) = LOWER(?) AND `author` != ?",
                (group_id, nickname, author),
            )
            if other_user:
                return False

            if not change_status:
                self_status = await session.FetchOne(
                    "SELECT `forceEdit` FROM nickName WHERE `group` = ? AND `author` = ?",
                    (group_id, author),
                )
                if self_status and self_status[0] == 1:
                    return False

            await session.Execute(
                "INSERT OR REPLACE INTO nickName (`group`, `author`, `name`, `forceEdit`) VALUES (?, ?, ?, ?)",
                (group_id, author, nickname, int(force_edit)),
            )
            await session.Commit()
            return True
        except Exception as exc:
            _log.error(f"设置昵称失败: {exc}")
            return False
        finally:
            await session.Close()


class MotdBlockRepository:
    """负责管理群级别的 Motd 屏蔽设置。"""

    def __init__(self, db_path: str = DATABASE_PATH):
        """记录仓储使用的数据库路径。"""
        self.db_path = db_path

    async def IsBlocked(self, group_id: str) -> bool:
        """判断当前群是否屏蔽了 Motd 功能。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            rows = await session.FetchAll(
                "SELECT 1 FROM blockMotd WHERE `group` = ?",
                (group_id,),
            )
        finally:
            await session.Close()
        return len(rows) > 0

    async def AddBlock(self, group_id: str):
        """为群开启 Motd 屏蔽。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "INSERT OR REPLACE INTO blockMotd (`group`) VALUES (?)",
                (group_id,),
            )
            await session.Commit()
        finally:
            await session.Close()
        return True

    async def RemoveBlock(self, group_id: str):
        """移除群的 Motd 屏蔽设置。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "DELETE FROM blockMotd WHERE `group` = ?",
                (group_id,),
            )
            await session.Commit()
        finally:
            await session.Close()
        return True


class AuthRepository:
    """负责管理 OpenId 与 QQ 的认证绑定。"""

    def __init__(self, db_path: str = DATABASE_PATH):
        """记录仓储使用的数据库路径。"""
        self.db_path = db_path

    async def GetBoundQQ(self, group_id: str, open_id: str):
        """读取成员在当前群绑定的 QQ 号。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            rows = await session.FetchAll(
                "SELECT `qq` FROM bindQQ WHERE `groupId` = ? AND `openId` = ?",
                (group_id, open_id),
            )
        finally:
            await session.Close()
        if rows:
            return rows[0][0]
        return None

    async def IsBound(self, group_id: str, open_id: str) -> bool:
        """判断成员是否已经完成 QQ 绑定。"""
        return await self.GetBoundQQ(group_id, open_id) is not None

    async def AddBinding(self, group_id: str, open_id: str, qq: str) -> bool:
        """写入或更新一条 QQ 绑定关系。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "INSERT OR REPLACE INTO bindQQ (groupId, openId, qq) VALUES (?, ?, ?)",
                (group_id, open_id, qq),
            )
            await session.Commit()
            return True
        except Exception as exc:
            _log.error(f"添加QQ绑定失败: {exc}")
            return False
        finally:
            await session.Close()

    async def DeleteBindingByOpenId(self, group_id: str, open_id: str) -> bool:
        """按群号和 OpenId 删除认证绑定。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "DELETE FROM bindQQ WHERE groupId = ? AND openId = ?",
                (group_id, open_id),
            )
            await session.Commit()
            return True
        except Exception as exc:
            _log.error(f"删除QQ绑定失败: {exc}")
            return False
        finally:
            await session.Close()

    async def DeleteBindingByQQ(self, qq: str) -> bool:
        """按 QQ 号删除认证绑定。"""
        session = SQLiteSession(self.db_path)
        await session.Connect()
        try:
            await session.Execute(
                "DELETE FROM bindQQ WHERE qq = ?",
                (qq,),
            )
            await session.Commit()
            return True
        except Exception as exc:
            _log.error(f"通过QQ删除绑定失败: {exc}")
            return False
        finally:
            await session.Close()


PendingBindStoreInstance = PendingBindStore()
BindRepositoryInstance = BindRepository()
AdminRepositoryInstance = AdminRepository()
NicknameRepositoryInstance = NicknameRepository()
MotdBlockRepositoryInstance = MotdBlockRepository()
AuthRepositoryInstance = AuthRepository()


__all__ = [
    "AdminRepository",
    "AdminRepositoryInstance",
    "AuthRepository",
    "AuthRepositoryInstance",
    "BindRepository",
    "BindRepositoryInstance",
    "DATABASE_PATH",
    "InitDb",
    "MotdBlockRepository",
    "MotdBlockRepositoryInstance",
    "NicknameRepository",
    "NicknameRepositoryInstance",
    "PendingBindStore",
    "PendingBindStoreInstance",
    "SQLiteSession",
]
