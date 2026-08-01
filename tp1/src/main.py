import os

def main():
    pids = [p for p in os.listdir("/proc") if p.isdigit()]
    print(f"Procesos visibles en /proc: {len(pids)}")

if __name__ == "__main__":
    main()
