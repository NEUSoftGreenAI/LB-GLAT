# -*- coding: utf-8 -*-


import pandas as pd
from torch.utils.tensorboard import SummaryWriter
from sklearn.metrics import roc_auc_score

from error.NoOptimError import NoOptimError
from dataset.cluster.loader import get_dataset_list
from utils.criterion_utils import *
from utils.common_utils import *
from train.GNN.train_config import *
from error.NoModelError import NoModelError
from utils.file_utils import get_absolute_path_by_path


logs_subfolder = "time" + str(time_end) + "__" + "".join([str(i) for i in gnns_forward_hidden.numpy()]) + "_" + \
                 "".join([str(i) for i in gnns_reverse_hidden.numpy()]) + "__" + \
                 str(project_hidden) + "_" + str(tsf_dim) + "_" + str(tsf_depth) + "_" + str(tsf_heads) + "_" + \
                 str(tsf_head_dim) + "_" + str(tsf_dropout) + str(vit_emb_dropout) + vit_pool + "__" + \
                 "".join([str(i) for i in linears_hidden.numpy()]) + "__2__dr" + str(decay_rate) + "__lr" + str(lr0)

###########################################
# Set the seed of random numbers generated by the CPU to facilitate the next reproduction of experimental results
setup_seed(seed)

###########################################
# Load data
data_list = get_dataset_list(seed)  # train_mask val_mask test_mask

###########################################
# Model and optimizer

if model_name in ["LB_GLAT"]:
    model = creat_LBGLAT()
elif model_name in ["GCN_FC"]:  # GCN
    model = creat_GCNFC()
elif model_name in ["Bi_GCN_FC"]:
    model = creat_BiGCNFC()
elif model_name in ["GCN_LTLA_FC"]:
    model = creat_GCNLTLAFC()
elif model_name in ["GAT_FC",]:  # GAT
    model = creat_GATFC()
elif model_name in ["Bi_GAT_FC"]:
    model = creat_BiGATFC()
elif model_name in ["GAT_LTLA_FC"]:
    model = creat_GATLTLAFC()
elif model_name in ["Bi_GAT_LTLA_FC"]:
    model = creat_BiGATLTLAFC()
elif model_name in ["SAGE_FC"]:  # GraphSAGE
    model = creat_SAGEFC()
elif model_name in ["Bi_SAGE_FC"]:
    model = creat_BiSAGEFC()
elif model_name in ["SAGE_LTLA_FC"]:
    model = creat_SAGELTLAFC()
elif model_name in ["Bi_SAGE_LTLA_FC"]:
    model = creat_BiSAGELTLAFC()
elif model_name in ["Bi_GEN_FC"]:  # DeeperGCN
    model = creat_BiGENFCModel()
else:
    raise NoModelError("No model is specified during training.")
paras_num = get_paras_num(model, model_name)

optimizer = None
if opt == "Adam":
    optimizer = optim.Adam(model.parameters(), betas=adam_beta, lr=lr0, weight_decay=weight_decay)
elif opt == "AdamW":
    optimizer = optim.AdamW(model.parameters(), betas=adam_beta, lr=lr0, weight_decay=weight_decay)
elif opt == "SGD":
    optimizer = optim.SGD(model.parameters(), lr=lr0, weight_decay=weight_decay)
elif opt == "RMSprop":
    optimizer = optim.RMSprop(model.parameters(), lr=lr0, weight_decay=weight_decay)
else:
    raise NoOptimError("No optim is specified during training.")

scheduler = optim.lr_scheduler.LambdaLR(optimizer, lr_lambda=lambda epoch: 1 / (1 + decay_rate * epoch),
                                        last_epoch=start_epoch - 1)
criterion = nn.CrossEntropyLoss(weight=torch.FloatTensor(criterion_weight))
# Cuda
model.to(device)
criterion.to(device)

###########################################
# tensorboard
logs_path = rf'{result_path}/{model_folder}/logs/{logs_subfolder}/{model_name}_paras{paras_num.get("Total")}_G{gnn_forward_layer_num}{gnn_reverse_layer_num}LA{1}L{linear_layer_num}O{1}_lr{lr0}dr{decay_rate}_bn{int(gnn_do_bn)}{int(linear_do_bn)}_gd{gnn_dropout}ld{linear_dropout}_{opt}_tw{criterion_weight[0]}_t{train_val_test_ratio[0]}{train_val_test_ratio[1]}rs{int(down_sampling)}{rs_NP_ratio}_epochs{epochs}'
if not os.path.exists(logs_path):
    os.makedirs(logs_path)
sw = SummaryWriter(log_dir=logs_path, flush_secs=5)


###########################################
# Train
def train_epoch(epoch):
    model.train()
    train_loss = 0
    train_target_num = torch.zeros((1, n_classes))
    train_predict_num = torch.zeros((1, n_classes))
    train_acc_num = torch.zeros((1, n_classes))
    train_predict_all = []
    train_target_all = []
    print("=" * 30 + f"{model_name} Train Epoch {epoch}" + "=" * 30)
    print(f"Learning Rate: {scheduler.get_lr()}")  # Display the current learning rate.
    for data in tqdm(data_list, desc=f"Train Epoch {epoch}: "):
        data.to(device)
        optimizer.zero_grad()
        output_mask = model(x=data.x, edge_index=data.edge_index, mask=data.train_mask)
        y_mask = data.y[data.train_mask]
        loss = criterion(output_mask, y_mask)
        train_loss += loss.item()
        loss.backward()  # Derive gradients.
        optimizer.step()

        predicted = output_mask.argmax(dim=1)  # Use the class with highest probability.
        pred_mask = torch.zeros(output_mask.size()).scatter_(1, predicted.cpu().view(-1, 1), 1.)
        train_predict_num += pred_mask.sum(0)  # Get the predicted quantity for each type in the data
        targ_mask = torch.zeros(output_mask.size()).scatter_(1, y_mask.cpu().view(-1, 1), 1.)
        train_target_num += targ_mask.sum(0)  # Get the number of each class in the data
        acc_mask = pred_mask * targ_mask
        train_acc_num += acc_mask.sum(0)  # Get the sample size correctly classified for each category
        targ_label, pred_pro = targ_pro(output_mask, y_mask)  # To calculate AUC
        train_target_all.extend(targ_label)
        train_predict_all.extend(pred_pro)
    scheduler.step()  # Update Learning Rate
    train_loss = train_loss / len(data_list)
    train_recall = (train_acc_num / train_target_num).cpu().detach().numpy()[0]
    train_precision = (train_acc_num / train_predict_num).cpu().detach().numpy()[0]
    train_F1 = (2 * train_recall * train_precision / (train_recall + train_precision))
    train_acc = (100. * train_acc_num.sum(1) / train_target_num.sum(1)).cpu().detach().numpy()[0]
    train_AUC = roc_auc_score(train_target_all, train_predict_all)

    if not fastmode:
        # Evaluate validation set performance separately,
        # deactivates dropout during validation run.
        val_loss, val_acc, val_precision, val_recall, val_F1, val_AUC = val()
        test_loss, test_acc, test_precision, test_recall, test_F1, test_AUC = test()
        print_epoch(epoch, train_loss, train_acc, train_precision, train_recall, train_F1, train_AUC,
                    val_loss, val_acc, val_precision, val_recall, val_F1, val_AUC,
                    test_loss, test_acc, test_precision, test_recall, test_F1, test_AUC)
        sw.add_scalars("Epoch_loss", {"train": train_loss, "val": val_loss, "test": test_loss}, epoch + 1)
        sw.add_scalars("Epoch_accuracy", {"train": train_acc, "val": val_acc, "test": test_acc}, epoch + 1)
        sw.add_scalars("Epoch_precision",
                       {"train": train_precision[0], "val": val_precision[0], "test": test_precision[0]}, epoch + 1)
        sw.add_scalars("Epoch_recall", {"train": train_recall[0], "val": val_recall[0], "test": test_recall[0]},
                       epoch + 1)
        sw.add_scalars("Epoch_F1-score", {"train": train_F1[0], "val": val_F1[0], "test": test_F1[0]}, epoch + 1)
        sw.add_scalars("Epoch_AUC", {"train": train_AUC, "val": val_AUC, "test": test_AUC}, epoch + 1)
        return train_loss, train_acc, train_precision[0], train_precision[1], \
            train_recall[0], train_recall[1], train_F1[0], train_F1[1], train_AUC, \
            val_loss, val_acc, val_precision[0], val_precision[1], \
            val_recall[0], val_recall[1], val_F1[0], val_F1[1], val_AUC, \
            test_loss, test_acc, test_precision[0], test_precision[1], \
            test_recall[0], test_recall[1], test_F1[0], test_F1[1], test_AUC
    else:
        print_epoch(epoch, train_loss, train_acc, train_precision, train_recall, train_F1, train_AUC)
        sw.add_scalar("Epoch_loss", train_loss, epoch + 1)
        sw.add_scalar("Epoch_accuracy", train_acc, epoch + 1)
        sw.add_scalar("Epoch_precision", train_precision[0], epoch + 1)
        sw.add_scalar("Epoch_recall", train_recall[0], epoch + 1)
        sw.add_scalar("Epoch_F1-score", train_F1[0], epoch + 1)
        sw.add_scalar("Epoch_AUC", train_AUC, epoch + 1)
        return train_loss, train_acc, train_precision[0], train_precision[1], \
            train_recall[0], train_recall[1], train_F1[0], train_F1[1], train_AUC, \
            0, 0, 0, 0, 0, 0, 0, 0, 0, \
            0, 0, 0, 0, 0, 0, 0, 0, 0


def val():
    model.eval()
    val_loss = 0
    # val_acc1 = 0
    val_target_num = torch.zeros((1, n_classes))
    val_predict_num = torch.zeros((1, n_classes))
    val_acc_num = torch.zeros((1, n_classes))
    val_predict_all = []
    val_target_all = []
    for data in tqdm(data_list, desc="Val Data: "):
        data.to(device)
        output_mask = model(x=data.x, edge_index=data.edge_index, mask=data.val_mask)
        y_mask = data.y[data.val_mask]
        val_loss += criterion(output_mask, y_mask).item()

        predicted = output_mask.argmax(dim=1)  # Use the class with highest probability.
        pred_mask = torch.zeros(output_mask.size()).scatter_(1, predicted.cpu().view(-1, 1), 1.)
        val_predict_num += pred_mask.sum(0)  # Get the predicted quantity for each type in the data
        targ_mask = torch.zeros(output_mask.size()).scatter_(1, y_mask.cpu().view(-1, 1), 1.)
        val_target_num += targ_mask.sum(0)  # Get the number of each class in the data
        acc_mask = pred_mask * targ_mask
        val_acc_num += acc_mask.sum(0)  # Get the sample size correctly classified for each category
        targ_label, pred_pro = targ_pro(output_mask, y_mask)  # To calculate AUC
        val_target_all.extend(targ_label)
        val_predict_all.extend(pred_pro)
    val_loss /= len(data_list)
    val_recall = (val_acc_num / val_target_num).cpu().detach().numpy()[0]
    val_precision = (val_acc_num / val_predict_num).cpu().detach().numpy()[0]
    val_F1 = 2 * val_recall * val_precision / (val_recall + val_precision)
    val_acc = (100. * val_acc_num.sum(1) / val_target_num.sum(1)).cpu().detach().numpy()[0]
    val_AUC = roc_auc_score(val_target_all, val_predict_all)
    return val_loss, val_acc, val_precision, val_recall, val_F1, val_AUC


# Test
def test():
    model.eval()
    test_loss = 0
    # test_acc1 = 0
    test_target_num = torch.zeros((1, n_classes))
    test_predict_num = torch.zeros((1, n_classes))
    test_acc_num = torch.zeros((1, n_classes))
    test_predict_all = []
    test_target_all = []
    for data in tqdm(data_list, desc="Test Data: "):
        data.to(device)
        output_mask = model(x=data.x, edge_index=data.edge_index, mask=data.test_mask)
        y_mask = data.y[data.test_mask]
        test_loss += criterion(output_mask, y_mask).item()

        predicted = output_mask.argmax(dim=1)  # Use the class with highest probability.
        pred_mask = torch.zeros(output_mask.size()).scatter_(1, predicted.cpu().view(-1, 1), 1.)
        test_predict_num += pred_mask.sum(0)  # Get the predicted quantity for each type in the data
        targ_mask = torch.zeros(output_mask.size()).scatter_(1, y_mask.cpu().view(-1, 1), 1.)
        test_target_num += targ_mask.sum(0)  # Get the number of each class in the data
        acc_mask = pred_mask * targ_mask
        test_acc_num += acc_mask.sum(0)  # Get the sample size correctly classified for each category
        targ_label, pred_pro = targ_pro(output_mask, y_mask)  # To calculate AUC
        test_target_all.extend(targ_label)
        test_predict_all.extend(pred_pro)
    test_loss /= len(data_list)
    test_recall = (test_acc_num / test_target_num).cpu().detach().numpy()[0]
    test_precision = (test_acc_num / test_predict_num).cpu().detach().numpy()[0]
    test_F1 = 2 * test_recall * test_precision / (test_recall + test_precision)
    test_acc = (100. * test_acc_num.sum(1) / test_target_num.sum(1)).cpu().detach().numpy()[0]
    test_AUC = roc_auc_score(test_target_all, test_predict_all)
    return test_loss, test_acc, test_precision, test_recall, test_F1, test_AUC


def print_epoch(epoch, train_loss, train_acc, train_precision, train_recall, train_F1, train_AUC,
                val_loss=0.0, val_acc=0.0, val_precision=None, val_recall=None, val_F1=None, val_AUC=0.0,
                test_loss=0.0, test_acc=0.0, test_precision=None, test_recall=None, test_F1=None, test_AUC=0.0):
    if not fastmode:
        print(f"[Epoch: {epoch}]: \n"
              f'[Train] Loss: {train_loss}, Accuracy: {train_acc}, '
              f'Precision P: {train_precision[0]} N: {train_precision[1]}, '  # Positive sample, negative sample
              f'Recall P: {train_recall[0]} N: {train_recall[1]}, '
              f'F1-score P: {train_F1[0]} N: {train_F1[1]}, AUC {train_AUC} \n'
              f'[Val] Loss: {val_loss}, Accuracy: {val_acc}, '
              f'Precision P: {val_precision[0]} N: {val_precision[1]}, '  # Positive sample, negative sample
              f'Recall P: {val_recall[0]} N: {val_recall[1]}, '
              f'F1-score P: {val_F1[0]} N: {val_F1[1]}, AUC {val_AUC} \n'
              f'[Test] Loss: {test_loss}, Accuracy: {test_acc}, '
              f'Precision P: {test_precision[0]} N: {test_precision[1]}, '  # Positive sample, negative sample
              f'Recall P: {test_recall[0]} N: {test_recall[1]}, '
              f'F1-score P: {test_F1[0]} N: {test_F1[1]}, AUC {test_AUC}')
    else:
        print(f"[Epoch: {epoch}]: \n"
              f'[Train] Loss: {train_loss}, Accuracy: {train_acc}, '
              f'Precision P: {train_precision[0]} N: {train_precision[1]}, '  # Positive sample, negative sample
              f'Recall P: {train_recall[0]} N: {train_recall[1]}, '
              f'F1-score P: {train_F1[0]} N: {train_F1[1]}, AUC {train_AUC} \n')


def train(epochs):
    print("=" * 30 + model_name + "=" * 30)
    print(model)
    print_model_state_dict(model)
    print_optimizer_state_dict(optimizer)
    columns = ["epoch", "train_loss", "train_acc", "train_precision_pos", "train_precision_neg",
               "train_recall_pos", "train_recall_neg", "train_F1_pos", "train_F1_neg", "train_AUC",
               "val_loss", "val_acc", "val_precision_pos", "val_precision_neg",
               "val_recall_pos", "val_recall_neg", "val_F1_pos", "val_F1_neg", "val_AUC",
               "test_loss", "test_acc", "test_precision_pos", "test_precision_neg",
               "test_recall_pos", "test_recall_neg", "test_F1_pos", "test_F1_neg", "test_AUC"]  # 28(1+9+9+9) 1 10
    results = pd.DataFrame(np.zeros(shape=(epochs, len(columns))), columns=columns)

    t_start = time.time()
    for epoch in range(epochs):
        evals = train_epoch(epoch)
        results.iloc[epoch, 0] = epoch + 1
        results.iloc[epoch, 1:] = evals
    print("Optimization Finished!")
    t_total = time.time() - t_start
    print("Total time elapsed: {:.4f}s".format(t_total))
    results["epoch"] = results["epoch"].astype(int)
    results_dir = f"{result_path}/{model_folder}/results/{logs_subfolder}"
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    results.to_csv(
        f'{results_dir}/{model_name}_paras{paras_num.get("Total")}_G{gnn_forward_layer_num}{gnn_reverse_layer_num}LA{1}L{linear_layer_num}O{1}_lr{lr0}dr{decay_rate}_bn{int(gnn_do_bn)}{int(linear_do_bn)}_gd{gnn_dropout}ld{linear_dropout}_{opt}_tw{criterion_weight[0]}_t{train_val_test_ratio[0]}{train_val_test_ratio[1]}rs{int(down_sampling)}{rs_NP_ratio}_epochs{epochs}_t{t_total:0.4f}.csv',
        mode='w', header=True, index=False)
    model_dir = f"{result_path}/{model_folder}/paras/{logs_subfolder}"
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
    torch.save(
        model,
        f'{model_dir}/{model_name}_paras{paras_num.get("Total")}_G{gnn_forward_layer_num}{gnn_reverse_layer_num}LA{1}L{linear_layer_num}O{1}_lr{lr0}dr{decay_rate}_bn{int(gnn_do_bn)}{int(linear_do_bn)}_gd{gnn_dropout}ld{linear_dropout}_{opt}_tw{criterion_weight[0]}_t{train_val_test_ratio[0]}{train_val_test_ratio[1]}rs{int(down_sampling)}{rs_NP_ratio}_epochs{epochs}.pth')
    print(results)


train(epochs)
