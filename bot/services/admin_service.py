from database.repository import require_admin


class AdminService:
    def __init__(self, repo):
        self.repo = repo

    async def save(self, actor_id, data, product_id=None, revision=None):
        require_admin(actor_id)
        return await self.repo.save_product(actor_id, data, product_id, revision)

    async def delete(self, actor_id, product_id, revision):
        require_admin(actor_id)
        await self.repo.delete_product(actor_id, product_id, revision)
