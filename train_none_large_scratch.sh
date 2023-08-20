export EPOCHS=15
export LR=5e-5
export FOLDER=math_scaffolding_none
export MODEL=gpt2-large
CUDA_VISIBLE_DEVICES=0 python train_scratch.py \
    --train_path data/${FOLDER}/src1_train.txt \
    --val_path data/${FOLDER}/src1_valid.txt \
    --test_path data/${FOLDER}/src1_test.txt \
    --epochs $EPOCHS \
    --lr $LR \
    --model $MODEL \
    > log.train.scratch.text.folder${FOLDER}.e${EPOCHS}.lr${LR}.model${MODEL} 2>&1&

export EPOCHS=15
export LR=1e-5
export FOLDER=math_scaffolding_none
CUDA_VISIBLE_DEVICES=1 python train_scratch.py \
    --train_path data/${FOLDER}/src1_train.txt \
    --val_path data/${FOLDER}/src1_valid.txt \
    --test_path data/${FOLDER}/src1_test.txt \
    --epochs $EPOCHS \
    --lr $LR \
    --model $MODEL \
    > log.train.scratch.text.folder${FOLDER}.e${EPOCHS}.lr${LR}.model${MODEL} 2>&1&

export EPOCHS=15
export LR=3e-4
export FOLDER=math_scaffolding_none
CUDA_VISIBLE_DEVICES=2 python train_scratch.py \
    --train_path data/${FOLDER}/src1_train.txt \
    --val_path data/${FOLDER}/src1_valid.txt \
    --test_path data/${FOLDER}/src1_test.txt \
    --epochs $EPOCHS \
    --lr $LR \
    --model $MODEL \
    > log.train.scratch.text.folder${FOLDER}.e${EPOCHS}.lr${LR}.model${MODEL} 2>&1&

export EPOCHS=15
export LR=1e-4
export FOLDER=math_scaffolding_none
CUDA_VISIBLE_DEVICES=3 python train_scratch.py \
    --train_path data/${FOLDER}/src1_train.txt \
    --val_path data/${FOLDER}/src1_valid.txt \
    --test_path data/${FOLDER}/src1_test.txt \
    --epochs $EPOCHS \
    --lr $LR \
    --model $MODEL \
    > log.train.scratch.text.folder${FOLDER}.e${EPOCHS}.lr${LR}.model${MODEL} 2>&1&

