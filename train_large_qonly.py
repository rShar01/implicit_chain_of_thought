import math
import torch
import sys
from torch.utils.data import Dataset, DataLoader
from torch.nn import CrossEntropyLoss
from transformers import AutoModelForCausalLM, AutoTokenizer, AdamW
import argparse
import os
import inspect
import tqdm
from data import CoTVAEDataset, VAEDataCollator
import logging
import random

torch.backends.cuda.matmul.allow_tf32 = True

# The flag below controls whether to allow TF32 on cuDNN. This flag defaults to True.
torch.backends.cudnn.allow_tf32 = True
torch.autograd.set_detect_anomaly(True)
random.seed(1234)
torch.manual_seed(1234)
logging.disable(logging.INFO) # disable INFO and DEBUG logging everywhere
# or 
logging.disable(logging.WARNING) # disable WARNING, INFO and DEBUG logging everywhere

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


def extract_answer(text):
    ans = text.strip().replace(',', '')
    return ans

def evaluate(model, model_q, dataloader, tokenizer, ctx, sigmas):
    model.eval()
    model_q.eval()
    total = 0
    word_correct = 0
    total_correct = 0
    total_loss = 0
    total_instances = 0
    for batch in tqdm.tqdm(dataloader):
        input_ids_cot = batch['input_ids_cot'].to(device)
        input_ids_nocot = batch['input_ids_nocot'].to(device)
        labels_cot = batch['labels_cot'].to(device)
        labels_cot_shift = batch['labels_cot_shift'].to(device)
        mask = labels_cot_shift.lt(0)
        labels_nocot = batch['labels_nocot'].to(device)
        with ctx:
            outputs_cot = model_q(input_ids=input_ids_cot, output_hidden_states=True)
            hidden_states_cot = outputs_cot.hidden_states

            # now, calculate q: batch_size, hidden_size
            batch_size = input_ids_cot.shape[0]
            hidden_size = hidden_states_cot[0].shape[-1]
            num_layers = len(hidden_states_cot) - 1
            ###relevant_ids = input_ids_cot.new_zeros(batch_size, num_layers+1).long()
            relevant_ids = input_ids_cot.new_zeros(batch_size, num_layers).long()
            first_ids = input_ids_cot.new_zeros(batch_size).long()
            for batch_id in range(batch_size):
                mask_id = mask[batch_id]
                mask_id_list = mask_id.cpu().tolist()
                first_id = mask_id_list.index(False)
                first_ids[batch_id] = first_id
                try:
                    last_id = mask_id_list[first_id:].index(True) + first_id
                except ValueError:
                    last_id = len(mask_id_list)

                ###layers = torch.arange(start=0, end=num_layers+1)
                layers = torch.arange(start=0, end=num_layers)
                ids = torch.round(first_id + layers * (last_id - 1 - first_id) / (num_layers))
                relevant_ids[batch_id] = ids
            #import pdb; pdb.set_trace()

            # time to compute q
            hidden_state_relevant_list = []
            for i, hidden_states in enumerate(hidden_states_cot[:-1]):
                hidden_state_relevant = hidden_states.gather(1, relevant_ids[:,i:(i+1)].unsqueeze(-1).expand(-1, -1, hidden_size)).squeeze(1)
                hidden_state_relevant_list.append(hidden_state_relevant + torch.randn_like(hidden_state_relevant) * sigmas[i])
            zs = hidden_state_relevant_list
            outputs_nocot = model.forward_zs(input_ids=input_ids_nocot, zs=hidden_state_relevant_list, first_ids=first_ids)
        logits = outputs_nocot.logits
        shift_logits = logits[..., :-1, :].contiguous()
        shift_labels = labels_nocot[..., 1:].contiguous()
        loss_fct = CrossEntropyLoss()
        loss = loss_fct(shift_logits.view(-1, shift_logits.size(-1)), shift_labels.view(-1))
        total_loss += loss.item() * labels_nocot[...,1:].ge(0).sum().item()

        labels_pred = logits.argmax(-1)
        correct = ((labels_pred[...,:-1] == labels_nocot[..., 1:]) * labels_nocot[..., 1:].ge(0)).sum().item()
        word_correct += correct
        total += labels_nocot[..., 1:].ge(0).sum().item()
        # TODO: generate and evaluate accuracy
        # activate beam search and early_stopping
        #import pdb; pdb.set_trace()

        for i, input_ids_single in enumerate(input_ids_nocot):
            total_instances += 1
            sep_idx = input_ids_single.tolist().index(tokenizer.eos_token_id)
            src = input_ids_single[:sep_idx+1]
            tgt = input_ids_single[sep_idx+1:]

            sep_idx = tgt.tolist().index(tokenizer.eos_token_id)
            tgt = tgt[:sep_idx]
            tgt_text = tokenizer.decode(tgt)
            ans = extract_answer(tgt_text)

            with torch.no_grad():
                with ctx:
                    beam_size = 5
                    #import pdb; pdb.set_trace()
                    beam_output = model.generate(
                        input_ids=src.view(1, -1),
                        max_new_tokens=100,
                        num_beams=beam_size,
                        early_stopping=True,
                        num_return_sequences=1,
                        first_ids=first_ids[i:(i+1)].expand(beam_size),
                        zs=[z[i:(i+1)].expand(beam_size, -1) for z in zs],
                    )
           
                    #import pdb; pdb.set_trace()
                    sep_idx = input_ids_single.tolist().index(tokenizer.eos_token_id)
                    pred_text = tokenizer.decode(beam_output[0][sep_idx+1:], skip_special_tokens=True)
            if i == 0:
                print ("Output:\n" + 100 * '-')
                print (pred_text)
                sys.stdout.flush()
            pred_ans = extract_answer(pred_text)
            #import pdb; pdb.set_trace()
            if ans == pred_ans:
                total_correct += 1
        #break

    word_accuracy = word_correct / total
    accuracy = total_correct / total_instances
    loss = total_loss / total
    ppl = math.exp(loss)
    return accuracy, word_accuracy, ppl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train_path', type=str, default='data/math_scaffolding_formula/src1_train.txt')
    parser.add_argument('--val_path', type=str, default='data/math_scaffolding_formula/src1_valid.txt')
    parser.add_argument('--test_path', type=str, default='data/math_scaffolding_formula/src1_test.txt')
    parser.add_argument('--epochs', type=int, default=5)
    parser.add_argument('--batch_size', type=int, default=5)
    parser.add_argument('--accumulate', type=int, default=1)
    parser.add_argument('--lr', type=float, default=5e-5)
    parser.add_argument('--max_grad_norm', type=float, default=1.0)
    parser.add_argument('--model', type=str, default='gpt2')
    args = parser.parse_args()

    print (args)
    
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    dtype = 'bfloat16' if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else 'float16' # 'float32', 'bfloat16', or 'float16', the latter will auto implement a GradScaler
    dtype = 'float32'
    ptdtype = {'float32': torch.float32, 'bfloat16': torch.bfloat16, 'float16': torch.float16}[dtype]
    print (ptdtype, dtype)
    model_q = AutoModelForCausalLM.from_pretrained(args.model).to(device).to(ptdtype)
    model = AutoModelForCausalLM.from_pretrained(args.model).to(device).to(ptdtype)
    # TODO: maybe use pretrained model here?
    #model.apply(model._init_weights)
    fused_available = 'fused' in inspect.signature(torch.optim.AdamW).parameters
    use_fused = fused_available
    extra_args = dict(fused=True) if use_fused else dict()
    num_layers = len(model.transformer.h)
    sigmas = torch.ones(num_layers).to(ptdtype).to(device)
    sigmas = torch.nn.Parameter(sigmas)
    #import pdb; pdb.set_trace()
    optimizer = torch.optim.AdamW([sigmas] + list(model.parameters())+list(model_q.parameters()), lr=args.lr)
    #optimizer_sigmas = torch.optim.SGD([sigmas], lr=args.lr)
    #optimizer = torch.optim.SGD([sigmas] + list(model.parameters())+list(model_q.parameters()), lr=args.lr)

    collate_fn = VAEDataCollator(tokenizer)
    train_dataset = CoTVAEDataset(tokenizer, args.train_path, 1024)
    train_dataloader = DataLoader(train_dataset, batch_size=args.batch_size, collate_fn=collate_fn, shuffle=True)
    val_dataset = CoTVAEDataset(tokenizer, args.val_path, 1024)
    val_dataloader = DataLoader(val_dataset, batch_size=args.batch_size, collate_fn=collate_fn, shuffle=True)

    torch.backends.cuda.matmul.allow_tf32 = True # allow tf32 on matmul
    torch.backends.cudnn.allow_tf32 = True # allow tf32 on cudnn
    # note: float16 data type will automatically use a GradScaler
    #compile = True # use PyTorch 2.0 to compile the model to be faster
    ctx = torch.amp.autocast(device_type='cuda', dtype=ptdtype)


    #accuracy, word_accuracy, ppl = evaluate(model, model_q, val_dataloader, tokenizer, ctx, sigmas)
    #print (f'Validation PPL: {ppl}. Validation Accuracy: {accuracy}. Word Accuracy: {word_accuracy}.')
    model.train()
    model_q.train()

    #model.eval()
    #model_q.eval()
    step = 0
    #import pdb; pdb.set_trace()
    for epoch in range(args.epochs):
        print(f"Epoch {epoch+1}") #TODO change epoch

        #model.save_pretrained("finetuned_gpt2")
        for batch in tqdm.tqdm(train_dataloader):
            #if epoch == 1:
            #    import pdb; pdb.set_trace()
            
            #import pdb; pdb.set_trace()
            input_ids_cot = batch['input_ids_cot'].to(device)
            input_ids_nocot = batch['input_ids_nocot'].to(device)
            labels_cot = batch['labels_cot'].to(device)
            labels_cot_shift = batch['labels_cot_shift'].to(device)
            mask = labels_cot_shift.lt(0)
            labels_nocot = batch['labels_nocot'].to(device)
            with ctx:
                outputs_cot = model_q(input_ids=input_ids_cot, output_hidden_states=True)
                hidden_states_cot = outputs_cot.hidden_states

                # now, calculate q: batch_size, hidden_size
                batch_size = input_ids_cot.shape[0]
                hidden_size = hidden_states_cot[0].shape[-1]
                num_layers = len(hidden_states_cot) - 1
                ###relevant_ids = input_ids_cot.new_zeros(batch_size, num_layers+1).long()
                relevant_ids = input_ids_cot.new_zeros(batch_size, num_layers).long()
                first_ids = input_ids_cot.new_zeros(batch_size).long()
                for batch_id in range(batch_size):
                    mask_id = mask[batch_id]
                    mask_id_list = mask_id.cpu().tolist()
                    first_id = mask_id_list.index(False)
                    first_ids[batch_id] = first_id
                    try:
                        last_id = mask_id_list[first_id:].index(True) + first_id
                    except ValueError:
                        last_id = len(mask_id_list)

                    ###layers = torch.arange(start=0, end=num_layers+1)
                    layers = torch.arange(start=0, end=num_layers)
                    ids = torch.round(first_id + layers * (last_id - 1 - first_id) / (num_layers))
                    relevant_ids[batch_id] = ids
                #import pdb; pdb.set_trace()

                # time to compute q
                hidden_state_relevant_list = []
                zs0 = []
                for i, hidden_states in enumerate(hidden_states_cot[:-1]):
                    hidden_state_relevant = hidden_states.gather(1, relevant_ids[:,i:(i+1)].unsqueeze(-1).expand(-1, -1, hidden_size)).squeeze(1)
                    zs0.append(hidden_state_relevant)
                    hidden_state_relevant_list.append(hidden_state_relevant + torch.randn_like(hidden_state_relevant) * sigmas[i])

                #for hidden_states in hidden_states_cot:
                #    hidden_states[mask] = 0 # batch_size, seq_len, hidden_size
                zs = hidden_state_relevant_list

                outputs_nocot = model.forward_zs(input_ids=input_ids_nocot, zs=zs, first_ids=first_ids)
                zs_p = outputs_nocot.zs_p
            #loss = outputs.loss
            logits = outputs_nocot.logits

            labels_pred = logits.argmax(-1)
            #import pdb; pdb.set_trace()
            correct = ((labels_pred[...,:-1] == labels_nocot[...,1:]) * labels_nocot[...,1:].ge(0)).sum().item()
            total = labels_nocot[...,1:].ge(0).sum()
            accuracy = correct / total

            kl = 0.
            #import pdb; pdb.set_trace()
            for z, zp, sigma_i in zip(zs0, zs_p, sigmas):
                kl += ((z-zp)*(z-zp)).sum() / sigma_i / sigma_i / 2 / total


            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = labels_nocot[..., 1:].contiguous()
            loss_fct = CrossEntropyLoss()
            nll = loss_fct(shift_logits.view(-1, shift_logits.size(-1)), shift_labels.view(-1)) 
            loss = nll + kl
            loss.div(args.accumulate).backward()
            #import pdb; pdb.set_trace()

            if step % args.accumulate == args.accumulate-1:
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                torch.nn.utils.clip_grad_norm_(model_q.parameters(), args.max_grad_norm)
                #torch.nn.utils.clip_grad_norm_([sigmas], args.max_grad_norm)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                #optimizer_sigmas.step()
                #optimizer_sigmas.zero_grad(set_to_none=True)
            loss = loss.item()
            try:
                ppl = math.exp(loss)
            except Exception as e:
                ppl = float('inf')
            ppl0 = math.exp(nll.item())
            if step % 100 == 0:
                print (f"Step: {step}. PPL: {ppl}. Loss: {loss}. PPL0: {ppl0}.Accuracy: {accuracy}")
                print (sigmas)
                sys.stdout.flush()
            step += 1
        #accuracy, word_accuracy, ppl = evaluate(model, model_q, train_dataloader, tokenizer, ctx, sigmas)
        accuracy, word_accuracy, ppl = evaluate(model, model_q, val_dataloader, tokenizer, ctx, sigmas)
        print (f'Epoch {epoch}. Validation PPL: {ppl}. Validation Accuracy: {accuracy}. Word Accuracy: {word_accuracy}.')
        print ('sigmas', sigmas)
        sys.stdout.flush()
        model.train()
        model_q.train()

if __name__ == "__main__":
    main()
