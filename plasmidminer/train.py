#!/usr/bin/python
from scipy.stats import randint as sp_randint
import sys
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import cPickle
import argparse
from termcolor import colored
import sobol_seq
from skbayes.rvm_ard_models import RVR,RVC
try:
	from sklearn.externals import joblib
	from sklearn.model_selection import RandomizedSearchCV
	from sklearn.ensemble import RandomForestClassifier
	from sklearn.linear_model import LogisticRegression
	from sklearn.svm import SVC
	from sklearn.model_selection import cross_val_score, train_test_split
	from sklearn.metrics import roc_curve
	from sklearn.metrics import auc
except ImportError:
	print 'This script requires sklearn to be installed!'

def savemodel(model, filename):
	with open(filename, 'wb') as fid:
		joblib.dump(model, fid, compress=9)

class Printer():
	"""Print things to stdout on one line dynamically"""

	def __init__(self, data):
		sys.stdout.write("\r\x1b[K" + data.__str__())
		sys.stdout.flush()

def creatematrix(features, kmer, args):
	stat = pd.read_csv(features, sep=",")
	kmer = pd.read_csv(kmer, sep="\t", header=None)
	kmer = kmer.iloc[:, :-1]
	id2 = stat.id.str.split("-", expand=True)  # split the string to get label
	id2 = id2.iloc[:, :-1]
	stat2 = stat.iloc[:, 1:]
	df = pd.concat([stat2.reset_index(drop=True), kmer],
				   axis=1)  # concat kmerand stat matrix
	df = pd.concat([id2, df], axis=1)
	df.columns.values[0] = "label"
	# encoding class labels as integers
	df.loc[df.label == 'positive', 'label'] = 1
	df.loc[df.label == 'negative', 'label'] = 0
	# get number of instances per group

	y = df['label'].tolist()  # extract label
	X = df.drop(df.columns[[0]], 1)  # remove label
	return X, y

def drawroc(clf, clf_labels, X_train, y_train, X_test, y_test):
	""" draw a roc curve for each model in clf, save as roc.png"""
	colors = ['black', 'orange', 'blue', 'green']
	linestyles = [':', '--', '-.', '-']
	for clf, label, clr, ls \
			in zip(clf, clf_labels, colors, linestyles):
		scores = cross_val_score(estimator=clf, X=X_train, y=y_train, cv=int(
			args.cv), scoring='roc_auc', n_jobs=-1, verbose=3)
		print("ROC AUC: %0.2f (+/- %0.2f) [%s]" %
			  (scores.mean(), scores.std(), label))
		y_pred = clf.fit(X_train, y_train).predict_proba(X_test)[:, 1]
		fpr, tpr, thresholds = roc_curve(y_true=y_test, y_score=y_pred)
		roc_auc = auc(x=fpr, y=tpr)
		plt.plot(fpr, tpr, color=clr, linestyle=ls,
				 label='%s (auc = %0.2f)' % (label, roc_auc))
	plt.legend(loc='lower right')
	plt.plot([0, 1], [0, 1], linestyle='--', color='gray', linewidth=2)
	plt.xlim([-0.1, 1.1])
	plt.ylim([-0.1, 1.1])
	plt.grid()
	plt.xlabel('False Positive Rate')
	plt.ylabel('True Positive Rate')
	# plt.tight_layout()
	plt.savefig('roc.png', dpi=300)
	plt.show()

def balanced_subsample(x, y, subsample_size=1.0):
	class_xs = []
	min_elems = None
	for yi in np.unique(y):
		elems = x[(y == yi)]
		class_xs.append((yi, elems))
		if min_elems == None or elems.shape[0] < min_elems:
			min_elems = elems.shape[0]
	use_elems = min_elems
	if subsample_size < 1:
		use_elems = int(min_elems * subsample_size)
	xs = []
	ys = []
	for ci, this_xs in class_xs:
		if len(this_xs) > use_elems:
			this_xs = this_xs.reindex(np.random.permutation(this_xs.index))
		x_ = this_xs[:use_elems]
		y_ = np.empty(use_elems)
		y_.fill(ci)
		xs.append(x_)
		ys.append(y_)
	xs = pd.concat(xs)
	ys = pd.Series(data=np.concatenate(ys), name='target')
	return xs, ys

def report(results, n_top=3):
	for i in range(1, n_top + 1):
		candidates = np.flatnonzero(results['rank_test_score'] == i)
		for candidate in candidates:
			print("Model with rank: {0}".format(i))
			print("Mean validation score: {0:.3f} (std: {1:.3f})".format(
				  results['mean_test_score'][candidate],
				  results['std_test_score'][candidate]))
			print("Parameters: {0}".format(results['params'][candidate]))
			print("")


def build_randomForest(X, y, args):
	Printer(colored('(training) ', 'green') +
			'searching for best parameters for random forest')
	# specify parameters and distributions to sample from
	param_dist = {"max_depth": [5, 4, 3, None],
				  "n_estimators": [500, 2000],
				  "max_features": sp_randint(1, 50),
				  "min_samples_split": sp_randint(2, 50),
				  "min_samples_leaf": sp_randint(1, 50),
				  "bootstrap": [True, False],
				  "criterion": ["gini", "entropy"]}
	clf = RandomForestClassifier()
	random_search = RandomizedSearchCV(clf, param_distributions=param_dist, scoring='accuracy', n_iter=args.iter, n_jobs=-1, refit=True)
	random_search.fit(X, y)
	acc = random_search.cv_results_['mean_test_score']
	filename = 'cv/randomforest_' + str(np.amax(acc)) + '.pkl'
	# save model
	savemodel(random_search, filename)
	return random_search

def build_logisticregression(X, y, args):
	Printer(colored('(training) ', 'green') +
			'searching for best parameters for logistic regression')
	# specify parameters and distributions to sample from
	param_dist = {"C": np.logspace(-9, 3, 13),
				  "solver": ['newton-cg', 'lbfgs', 'liblinear', 'sag'],
				  "dual": [False],
				  "tol": np.logspace(-9, 3, 13)
				  }
	clf = LogisticRegression(penalty='l2')
	random_search = RandomizedSearchCV(clf, param_distributions=param_dist, scoring='accuracy', n_iter=args.iter, n_jobs=-1, refit=True)
	random_search.fit(X, y)
	acc = random_search.cv_results_['mean_test_score']
	filename = 'cv/logisticregression_' + str(np.amax(acc)) + '.pkl'
	savemodel(random_search, filename)
	return random_search


def build_svc(X, y, args):
	Printer(colored('(training) ', 'green') +
			'searching for best parameters for SVC')
	# specify parameters and distributions to sample from
	if (args.sobol):
		param_dist = {'C': sobol_seq.i4_sobol_generate(1, int(args.sobol_num)) * 2** (15),
				  'gamma': sobol_seq.i4_sobol_generate(1, int(args.sobol_num)), 'kernel': ['linear', 'rbf']}
	else:
		param_dist = {'C': pow(2.0, np.arange(-10, 11, 0.1)),
		'gamma': pow(2.0, np.arange(-10, 11, 0.1)), 'kernel': ['linear', 'rbf']}
	clf = SVC(probability=True)
	random_search = RandomizedSearchCV(clf, param_distributions=param_dist, scoring='accuracy', n_iter=args.iter, n_jobs=-1, refit=True)
	random_search.fit(X, y)

	acc = random_search.cv_results_['mean_test_score']
	filename = 'cv/svc_' + str(np.amax(acc)) + '.pkl'
	savemodel(random_search, filename)
	return random_search
#   report(random_search.cv_results_)


def build_rvc(X, y, args):
	Printer(colored('(training) ', 'green') +
			'searching for best parameters for RVC')
	# specify parameters and distributions to sample from
	if (args.sobol):
		param_dist = {'gamma': sobol_seq.i4_sobol_generate(1, int(args.sobol_num)),
				  'kernel': ['linear', 'rbf']}
	else:
		param_dist = {'gamma': pow(2.0, np.arange(-10, 11, 0.1)),
		'kernel': ['linear', 'rbf']}

	clf = RVC(kernel='rbf', gamma=1)
	random_search = RandomizedSearchCV(clf, param_distributions=param_dist, scoring='accuracy',
									   n_iter=args.iter, n_jobs=-1, refit=True)
	random_search.fit(X, y)

#   report(random_search.cv_results_)

	acc = random_search.cv_results_['mean_test_score']
	filename = 'cv/rvc_' + str(np.amax(acc)) + '.pkl'
	# save model
	savemodel(random_search, filename)
	return random_search

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument('-t', '--test_size', action='store', dest='test_size',
						help='size of test set from whole dataset in percent', default=30)
	parser.add_argument('-r', '--random_size', action='store', dest='random_size',
						help='size of balanced random subset of data in percent', default=10)
	parser.add_argument('-i', '--iterations', action='store', dest='iter',
						help='number of random iterationsfor hyperparameter optimization', default=10)
	parser.add_argument('-c', '--cv', action='store', dest='cv',
						help='cross validation size (e.g. 10 for 10-fold cross validation)', default=3)
	parser.add_argument('--lhs', dest='lhs',
						action='store_true', help='optimize parameters')
	parser.add_argument('--roc', dest='roc',
						action='store_true', help='plot ROC curve')
	parser.add_argument('--balance', dest='balance',
						action='store_true', help='balance dataset')
	parser.add_argument('--sobol', dest='sobol',
						action='store_true', help='use sobol sequence for random search')
	parser.add_argument('--sobol_num', dest='sobol_num',
						action='store', help='number of sequence instances in sobol sequence')
	parser.add_argument('--version', action='version', version='%(prog)s 1.0')
	args = parser.parse_args()

	# load/preprocess data
	Printer(colored('(preprocessing) ', 'green') + 'import data')
	X, y = creatematrix('dat/train.features.clear2.csv',
						'dat/train.features.kmer', args)

	# generate a random subset
	Printer(colored('(preprocessing) ', 'green') + 'generate a random subset')
	X_sub, y_sub = balanced_subsample(X, y, subsample_size=0.1)

	# split train/testset
	Printer(colored('(preprocessing) ', 'green') + 'generate train/test set')
	X_train, X_test, y_train, y_test = train_test_split(
		X_sub, y_sub, test_size=0.3)

	if not os.path.exists('cv'):
		os.makedirs('cv')

	# build model
	rf_model = build_randomForest(X_train, y_train, args)
#   lg_model = build_logisticregression(X_train, y_train, args)
	svc_model = build_svc(X_train, y_train, args)
	rvc_model = build_rvc(X_train, y_train, args)

	# save model
#  Printer(colored('(training) ', 'green') + 'save model')
#  with open('model.pkl', 'wb') as fid:
#      cPickle.dump(pipe, fid)

	# draw ROC
#  if(args.roc):
#      Printer(colored('(training) ', 'green') + 'draw ROC curve')
#      drawroc(all_clf, clf_labels, X_train, y_train, X_test, y_test)
