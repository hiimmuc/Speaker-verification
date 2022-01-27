import glob
import os
import sys
import time

from callbacks.earlyStopping import *
from dataloader import get_data_loader
from model import SpeakerNet
from utils import *


def train(args):
    # Initialise directories
    model_save_path = args.save_path + f"/{args.model}/model"
    result_save_path = args.save_path + f"/{args.model}/result"

    # init
    it = 1
    min_loss = float("inf")
    min_eer = float("inf")
    
    # load state from log file
    if os.path.isfile(os.path.join(model_save_path, "model_state.log")):
        start_it, start_lr, _ = read_log_file(os.path.join(model_save_path, "model_state.log"))
    else:
        start_it = 1
        start_lr = args.lr
        
    # Load model weights
    model_files = glob.glob(os.path.join(model_save_path, 'model_state_*.model'))
    model_files.sort()

    eerfiles = glob.glob(os.path.join(model_save_path, 'model_state_*.eer'))
    eerfiles.sort()

    # if exists best model load from it
    prev_model_state = None
    if start_it > 1:
        if os.path.exists(f'{model_save_path}/best_state.model'):
            prev_model_state = f'{model_save_path}/best_state.model'
        elif args.save_model_last:
            if os.path.exists(f'{model_save_path}/last_state.model'):
                prev_model_state = f'{model_save_path}/last_state.model'
        else:
            prev_model_state = model_files[-1]

        # get the last stopped iteration, model_state_xxxxxx.eer, so 12 is index of number sequence
#         start_it = int(os.path.splitext(
#             os.path.basename(eerfiles[-1]))[0][12:]) + 1

        if args.max_epoch > start_it:
            it = int(start_it)
        else:
            it = 1
    
    # Load models
    s = SpeakerNet(**vars(args))
        
    if args.initial_model:
        s.loadParameters(args.initial_model)
        print("Model %s loaded!" % args.initial_model)
        it = 1
    elif prev_model_state:
        s.loadParameters(prev_model_state)
        print("Model %s loaded from previous state!" % prev_model_state)
        args.lr = start_lr
    else:
        print("Train model from scratch!")
        it = 1
    
    if it == 1:
        # remove old eerfiles
        for old_file in eerfiles:
            if os.path.exists(old_file):
                os.remove(old_file)

    # schedule the learning rate to stopped epoch
#     if args.callbacks in ['steplr', 'cosinelr']:
#         for _ in range(0, it - 1):
#             s.__scheduler__.step()
#     elif args.callbacks == 'auto':
#         try:
#             it, lr, _ = read_log_file(model_save_path + "/model_state.log")
#         except:
#             pass
        
    # Write args to score_file
    settings_file = open(result_save_path + '/settings.txt', 'a+')
    score_file = open(result_save_path + "/scores.txt", "a+")
    # summary settings
    settings_file.write(
        f'\n[TRAIN]------------------{time.strftime("%Y-%m-%d %H:%M:%S")}------------------\n')
    score_file.write(
        f'\n[TRAIN]------------------{time.strftime("%Y-%m-%d %H:%M:%S")}------------------\n')
    # write the settings to settings file
    for items in vars(args):
        # print(items, vars(args)[items])
        settings_file.write('%s %s\n' % (items, vars(args)[items]))
    settings_file.flush()

    # Initialise data loader
    train_loader = get_data_loader(args.train_list, **vars(args))

    if args.early_stop:
        early_stopping = EarlyStopping(patience=args.es_patience)

    # Training loop
    while True:
        clr = [x['lr'] for x in s.__optimizer__.param_groups]

        print(time.strftime("%Y-%m-%d %H:%M:%S"), it,
              "[INFO] Training %s with LR %f..." % (args.model, max(clr)))

        # Train network
        loss, trainer = s.fit(loader=train_loader, epoch=it)
        
        # save best model
        if loss == min(min_loss, loss):
            print(f"[INFO] Loss reduce from {min_loss} to {loss}. Save the best state")
            s.saveParameters(model_save_path + "/best_state.model")
            if args.early_stop:
                early_stopping.counter = 0  # reset counter of early stopping

        min_loss = min(min_loss, loss)

        # Validate and save
        if args.test_interval > 0 and it % args.test_interval == 0:

            #             print(time.strftime("%Y-%m-%d %H:%M:%S"), it, "[INFO] Evaluating...")

            sc, lab, _ = s.evaluateFromList(args.test_list,
                                            cohorts_path=None,
                                            eval_frames=args.eval_frames)
            result = tuneThresholdfromScore(sc, lab, [1, 0.1])

            min_eer = min(min_eer, result[1])

            print("[INFO] Evaluating ",
                  time.strftime("%H:%M:%S"),
                  "LR %f, TEER/TAcc %2.2f, TLOSS %f, VEER %2.4f, MINEER %2.4f" %
                  (max(clr), trainer, loss, result[1], min_eer))
            score_file.write(
                "IT %d, LR %f, TEER/TAcc %2.2f, TLOSS %f, VEER %2.4f, MINEER %2.4f\n"
                % (it, max(clr), trainer, loss, result[1], min_eer))

            score_file.flush()

            # NOTE: consider save last state only or not, save only eer as the checkpoint for iterations
            if args.save_model_last:
                s.saveParameters(model_save_path + "/last_state.model")
            else:
                s.saveParameters(model_save_path + "/model_state_%06d.model" % it)

            with open(model_save_path + "/model_state_%06d.eer" % it, 'w') as eerfile:
                eerfile.write('%.4f, ' % result[1])
                
            with open(os.path.join(model_save_path , "/model_state.log"), 'w+') as log_file:
                log_file.write(f"Epoch:{it}, LR:{max(clr)}, EER: {result[1]}")

            plot_from_file(result_save_path, show=False)
        else:
            # test interval < 0 -> train continuously
            print("[INFO] Training at", time.strftime("%H:%M:%S"),
                  "LR %f, Accuracy: %2.2f, Loss: %f" % (max(clr), trainer, loss))
            score_file.write("IT %d, LR %f, TEER/TAcc %2.2f, TLOSS %f\n" %
                             (it, max(clr), trainer, loss))

            with open(os.path.join(model_save_path , "/model_state.log"), 'w') as log_file:
                log_file.write(f"Epoch:{it}, LR:{max(clr)}, EER: {0}")

            score_file.flush()
            
            plot_from_file(result_save_path, show=False)

        if it >= args.max_epoch:
            score_file.close()
            sys.exit(1)

        if args.early_stop:
            early_stopping(loss)
            if early_stopping.early_stop:
                score_file.close()
                sys.exit(1)

        it += 1

# ============================ END =============================