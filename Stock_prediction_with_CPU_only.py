import neptune
import os

# ensures no GPU usage for traditional Keras LSTM
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = '-1'

# Connect your script to Neptune.ai
my_api_token = 'eyJhcGlfYWRkcmVzcyI6Imh0dHBzOi8vYXBwLm5lcHR1bmUuYWkiLCJhcGlfdXJsIjoiaHR0cHM6Ly9hcHAubmVwdHVuZS5haSIsImFwaV9rZXkiOiI0Yjc2MzJiOS04ZTc0LTRjN2UtOWQ2MC01ZDkyNjNhMTc5YjcifQ=='
project = neptune.init(api_token=my_api_token,
                       project_qualified_name='roverttt/stocks')

import pandas as pd
import numpy as np

np.random.seed(42)

from datetime import date

from sklearn.preprocessing import MinMaxScaler, StandardScaler
from keras.models import Sequential, Model
from keras.models import Model
from keras.layers import Dense, Dropout, LSTM, Input, Activation, concatenate

import tensorflow as tf

tf.random.set_seed(42)

import matplotlib.pyplot as plt
import datetime as dt
import urllib.request, json

working_directory = os.getcwd()
os.chdir(working_directory)

data_source = 'alphavantage'  # alphavantage

# Get the data off alphavantage website
if data_source == 'alphavantage':
    api_key = '5TBXRN48HML2J65T'
    # stock ticker symbol
    # ticker = 'AAPL' # apple
    # ticker = 'KO' # coca cola
    ticker = 'WFC' # wells fargo

    # JSON file with all the stock prices data
    url_string = "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=%s&outputsize=full&apikey=%s" % (
    ticker, api_key)

    # Save data to this file
    fileName = 'stock_market_data-%s.csv' % ticker

    ### get the low, high, close, and open prices
    if not os.path.exists(fileName):
        with urllib.request.urlopen(url_string) as url:
            data = json.loads(url.read().decode())
            # pull stock market data
            data = data['Time Series (Daily)']
            df = pd.DataFrame(columns=['Date', 'Low', 'High', 'Close', 'Open'])
            for key, val in data.items():
                date = dt.datetime.strptime(key, '%Y-%m-%d')
                data_row = [date.date(), float(val['3. low']), float(val['2. high']),
                            float(val['4. close']), float(val['1. open'])]
                df.loc[-1, :] = data_row
                df.index = df.index + 1
        df.to_csv(fileName)

    else:
        print('Loading data from local')
        df = pd.read_csv(fileName)

stockprices = df.sort_values('Date')


# calculates root mean squared error
def calculate_rmse(y_true, y_pred):
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
    return rmse


# calculates mean absolute percentage error
def calculate_mape(y_true, y_pred):
    y_pred, y_true = np.array(y_pred), np.array(y_true)
    mape = np.mean(np.abs((y_true - y_pred) / y_true)) * 100
    return mape


# Split the time-series data into training seq X and output value Y
# inputs:
# data: dataset
# N: window size (in days)
# offset: position of split
def extract_seqX_outcomeY(data, N, offset):
    X, y = [], []

    for i in range(offset, len(data)):
        X.append(data[i - N:i])
        y.append(data[i])

    return np.array(X), np.array(y)


#### Train-Test split for time-series ####
test_ratio = 0.2
training_ratio = 1 - test_ratio

train_size = int(training_ratio * len(stockprices))
test_size = int(test_ratio * len(stockprices))

print("train_size: " + str(train_size))
print("test_size: " + str(test_size))

train = stockprices[:train_size][['Date', 'Close']]
test = stockprices[train_size:][['Date', 'Close']]

###================= simple MA
stockprices = stockprices.set_index('Date')


### For meduim-term trading
def plot_stock_trend(var, cur_title, stockprices=stockprices, logNeptune=True, logmodelName='Simple MA'):
    ax = stockprices[['Close', var, '200day']].plot(figsize=(20, 10))
    plt.grid(False)
    plt.title(cur_title)
    plt.axis('tight')
    plt.ylabel('Stock Price ($)')

    if logNeptune:
        npt_exp.log_image(f'Plot of Stock Predictions with {logmodelName}', ax.get_figure())


def calculate_perf_metrics(var, logNeptune=True, logmodelName='Simple MA'):
    # calculate evaluation metrics(root mean squared error and mean absolute percentage error)
    rmse = calculate_rmse(np.array(stockprices[train_size:]['Close']), np.array(stockprices[train_size:][var]))
    mape = calculate_mape(np.array(stockprices[train_size:]['Close']), np.array(stockprices[train_size:][var]))

    # send data to neptune
    if logNeptune:
        npt_exp.send_metric('RMSE', rmse)
        npt_exp.log_metric('RMSE', rmse)

        npt_exp.send_metric('MAPE (%)', mape)
        npt_exp.log_metric('MAPE (%)', mape)

    return rmse, mape


# 20 days to represent the 22 trading days in a month
window_size = 50
CURRENT_MODEL = 'LSTM'

# elif CURRENT_MODEL == 'LSTM':
if CURRENT_MODEL == 'LSTM':
    layer_units, optimizer = 50, 'adam'
    cur_epochs = 15
    cur_batch_size = 20

    cur_LSTM_pars = {'units': layer_units,
                     'optimizer': optimizer,
                     'batch_size': cur_batch_size,
                     'epochs': cur_epochs
                     }

    npt_exp = project.create_experiment(name='LSTM',
                                        params=cur_LSTM_pars,
                                        description='stock-prediction-machine-learning',
                                        tags=['stockprediction', 'LSTM', 'neptune'])

    # use the past N stock prices for training to predict the N+1th closing price

    # scale
    scaler = StandardScaler()
    scaled_data = scaler.fit_transform(stockprices[['Close']])
    scaled_data_train = scaled_data[:train.shape[0]]

    X_train, y_train = extract_seqX_outcomeY(scaled_data_train, window_size, window_size)


    # create lstm model
    def Run_LSTM(X_train, layer_units=50, logNeptune=True, NeptuneProject=None):
        inp = Input(shape=(X_train.shape[1], 1))

        x = LSTM(units=layer_units, return_sequences=True)(inp)
        x = LSTM(units=layer_units)(x)
        out = Dense(1, activation='linear')(x)
        model = Model(inp, out)

        # Compile the LSTM neural net
        model.compile(loss='mean_squared_error', optimizer='adam')

        ## log to Neptune, e.g., set NeptuneProject = npt_exp
        if logNeptune:
            model.summary(print_fn=lambda x: NeptuneProject.log_text('model_summary', x))

        return model


    model = Run_LSTM(X_train, layer_units=layer_units, logNeptune=True, NeptuneProject=npt_exp)

    history = model.fit(X_train, y_train, epochs=cur_epochs, batch_size=cur_batch_size,
                        verbose=1, validation_split=0.1, shuffle=True)


    # predict stock prices using past window_size stock prices
    def preprocess_testdat(data=stockprices, scaler=scaler, window_size=window_size, test=test):
        raw = data['Close'][len(data) - len(test) - window_size:].values
        raw = raw.reshape(-1, 1)
        raw = scaler.transform(raw)

        X_test = []
        for i in range(window_size, raw.shape[0]):
            X_test.append(raw[i - window_size:i, 0])

        X_test = np.array(X_test)

        X_test = np.reshape(X_test, (X_test.shape[0], X_test.shape[1], 1))
        return X_test


    X_test = preprocess_testdat()

    predicted_price_ = model.predict(X_test)
    predicted_price = scaler.inverse_transform(predicted_price_)

    # Plot predicted price vs actual closing price
    test['Predictions_lstm'] = predicted_price

    # Evaluate performance
    rmse_lstm = calculate_rmse(np.array(test['Close']), np.array(test['Predictions_lstm']))
    mape_lstm = calculate_mape(np.array(test['Close']), np.array(test['Predictions_lstm']))
    npt_exp.send_metric('RMSE', rmse_lstm)
    npt_exp.log_metric('RMSE', rmse_lstm)

    npt_exp.send_metric('MAPE (%)', mape_lstm)
    npt_exp.log_metric('MAPE (%)', mape_lstm)


    # Plot predictions / send data to neptune
    def plot_stock_trend_lstm(train, test, logNeptune=True):
        fig = plt.figure(figsize=(20, 10))
        plt.plot(train['Date'], train['Close'], label='Train Closing Price')
        plt.plot(test['Date'], test['Close'], label='Test Closing Price')
        plt.plot(test['Date'], test['Predictions_lstm'], label='Predicted Closing Price')
        plt.title('LSTM Model')
        plt.xlabel('Date')
        plt.ylabel('Stock Price ($)')
        plt.legend(loc="upper left")

        if logNeptune:
            npt_exp.log_image('Plot of Stock Predictions with LSTM', fig)


    plot_stock_trend_lstm(train, test)








