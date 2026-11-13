from backend.db import migrate
if __name__=='__main__':
    migrate()
    print('Schema version 2 ready')
