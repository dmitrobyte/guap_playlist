class ApiError(Exception):
    """Ошибка API с понятным кодом и сообщением на русском."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
