import argparse
# Modify the data to have two problems per line 

def chunk(first, second):
  first_seg = first.split("||")
  first_parts = [first_seg[0]] + first_seg[1].split("####")
  first_parts[2] = first_parts[2][:len(first_parts[2])-1]

  second_seg = second.split("||")
  second_parts = [second_seg[0]] + second_seg[1].split("####")
  second_parts[2] = second_parts[2][:len(second_parts[2])-1]
  print(first_parts)
  print(second_parts)

  return first_parts, second_parts 


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=str, help="path to file with training data")
    parser.add_argument("--out", type=str, help="path to output file")
    parser.add_argument("--num_lines", default=1, type=int, help="number of lines to combine")
    # TODO: add some randomization in the future
    args = parser.parse_args()
    print(args.path)
    with open(f"{args.path}") as f, open(f"{args.out}", "w") as o:
        counter = args.num_lines
        while counter > 0:
            first, second = chunk(f.readline(), f.readline())
            concat = f"{first[0]}, {second[0]}||{first[1]},{second[1]}####{first[2]},{second[2]}"
            o.write(concat +"\n")
            counter -= 1





