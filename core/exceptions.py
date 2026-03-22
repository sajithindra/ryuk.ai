class RyukError(Exception):
    """Base class for all Ryuk AI exceptions."""
    pass

class ProcessorError(RyukError):
    """Raised when an error occurs in the AI processing pipeline."""
    pass

class DatabaseError(RyukError):
    """Raised when an error occurs during database operations (Redis/Mongo)."""
    pass

class ConfigurationError(RyukError):
    """Raised when there is an issue with the system configuration."""
    pass

class IdentityError(RyukError):
    """Raised when there is an issue with identity management or indexing."""
    pass

class CommunicationError(RyukError):
    """Raised when there is an error in server/client communication."""
    pass
