
import os

target_file = 'frontend/app/page.tsx'
start_line = 933 # 1-based
end_line = 1028 # 1-based

with open(target_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = start_line - 1
end_idx = end_line

# Verification
print(f"Verifying line {start_line}: {lines[start_idx].strip()}")
if '</Group >' not in lines[start_idx]:
    print("MISMATCH AT START")
    # exit(1) # Proceed with caution or adjust?
    # Actually, let's print context if mismatch
    for i in range(start_idx-2, start_idx+3):
        print(f"{i+1}: {lines[i].strip()}")

print(f"Verifying line {end_line}: {lines[end_idx-1].strip()}")
if '</Modal >' not in lines[end_idx-1]:
    print("MISMATCH AT END") 
    exit(1)

new_lines = lines[:start_idx] + lines[end_idx:]

with open(target_file, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Success")
