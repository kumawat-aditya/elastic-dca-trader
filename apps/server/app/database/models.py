from sqlalchemy import Column, Integer, String, Text
from app.database.session import Base

class PresetDB(Base):
    """
    Stores a List of GridRows as a serialized JSON string.
    Leaves user's Start Limits and TP/SL values completely untouched.
    """
    __tablename__ = "presets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    # Storing the dumped JSON of List[GridRow]
    rows_json = Column(Text, nullable=False)