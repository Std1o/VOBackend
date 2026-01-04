from database import engine
from tables import Base


def main():
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    main()